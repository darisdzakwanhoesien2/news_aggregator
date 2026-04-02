"""
────────────────────────────────────────────────────────────────────────────────
MCQ LLM Verification & Scoring Page
────────────────────────────────────────────────────────────────────────────────
Workflow:
  1. Select a company folder
  2. Select an MCQ answer JSON (manual or LLM)
  3. LLM verifies each answer against OCR text
  4. Displays score, pillar breakdown, and per-question reasoning
"""

import argparse
import html
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
import shutil

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MCQ LLM Verification",
    page_icon="🔍",
    layout="wide",
)

# ── Paths & env ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[1]   # new_app/
DATA_DIR = BASE_DIR / "data"
load_dotenv(BASE_DIR / ".env")

OPENROUTER_API_URL    = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_MODELS_URL = os.getenv("OPENROUTER_MODELS_URL", "https://openrouter.ai/api/v1/models")
DEFAULT_MODEL         = "meta-llama/llama-3.1-8b-instruct:free"

# ── Score mapping: selected choice → numeric score ─────────────────────────────
# A = full compliance (3), B = partial (2), C = planning (1), D = no (0)
CHOICE_SCORE = {"A": 3, "B": 2, "C": 1, "D": 0, "": 0}
MAX_SCORE_PER_QUESTION = 3


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS — DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════

def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_json(p: Path, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_table_line(line: str) -> bool:
    return line.strip().startswith("|") or re.match(r"^\s*\|.*\|\s*$", line)


def clean_markdown(md: str) -> str:
    # decode HTML entities
    md = html.unescape(md)

    # remove image-only lines like ![img-0.jpeg](img-0.jpeg) but keep inline images if desired
    md = re.sub(r"^\s*!\[[^\]]*\]\([^\)]+\)\s*$\n?", "", md, flags=re.M)

    # remove stray long base64 fragments if they accidentally ended up in markdown
    md = re.sub(r"data:image\/[a-zA-Z]+;base64,[A-Za-z0-9+/=\s]+", "", md)

    # Fix hyphenation at line ends: "exam-\nple" -> "example"
    md = re.sub(r"(\w)-\n(\w)", r"\1\2", md)

    # Split into lines and join lines into paragraphs while preserving headings and tables
    lines = md.splitlines()
    out_lines: List[str] = []
    inside_table = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        # detect table region start/stop
        if is_table_line(line):
            inside_table = True
            out_lines.append(line.rstrip())
            continue
        else:
            if inside_table and stripped == "":
                inside_table = False

        # preserve headings, lists, blockquotes and explicit section separators
        if re.match(r"^(#{1,6}\s)|^(\s*[-*+]\s)|^>\s|^---\s*$|^\s*\d+\.\s", line):
            out_lines.append(line.rstrip())
            continue

        # if we are in a paragraph: join broken lines (single newline -> space)
        # join lines that are not empty and next line is not a heading/table/list
        if stripped == "":
            out_lines.append("")  # preserve paragraph break
            continue

        # look ahead: if next line is end or special, keep newline; else join
        next_line = lines[i+1] if i+1 < len(lines) else ""
        if next_line.strip() == "" or re.match(r"^(#{1,6}\s)|^(\s*[-*+]\s)|^>\s|^\s*\d+\.\s", next_line) or is_table_line(next_line):
            out_lines.append(line.rstrip())
        else:
            # join with next line (space)
            out_lines.append(line.rstrip() + " ")  # trailing space used to merge in next iteration

    # now collapse sequences of "word␣ \nword␣ " that were produced above
    joined = "\n".join(out_lines)
    # collapse multiple spaces
    joined = re.sub(r"[ \t]{2,}", " ", joined)
    # fix accidental space before punctuation that appeared after joining
    joined = re.sub(r"\s+([,.;:!?])", r"\1", joined)
    # collapse >2 consecutive blank lines to 2
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip() + "\n"


def write_pages_from_ocr_json(doc_dir: Path, ocr_json_path: Path):
    data = load_json(ocr_json_path)
    pages = data.get("pages", [])
    pages_dir = doc_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for p in pages:
        idx = p.get("index", 0)
        md = p.get("markdown", "")
        cleaned = clean_markdown(md)
        out = pages_dir / f"page_{idx:04d}.md"
        out.write_text(cleaned, encoding="utf-8")

    # optionally update the json's markdown fields to cleaned version
    for p in pages:
        p["markdown"] = clean_markdown(p.get("markdown", ""))
    save_json(ocr_json_path, data)
    print(f"Written {len(pages)} cleaned pages to {pages_dir}")


def clean_pages_folder(doc_dir: Path):
    pages_dir = doc_dir / "pages"
    if not pages_dir.exists():
        print("No pages/ folder to clean.")
        return
    for md in sorted(pages_dir.glob("*.md")):
        txt = md.read_text(encoding="utf-8")
        cleaned = clean_markdown(txt)
        md.write_text(cleaned, encoding="utf-8")
    print(f"Cleaned markdown in {pages_dir}")


# Ensure OCR helper moved here so it's defined before being called in main
def list_ocr_candidates(company_dir: Path) -> dict:
    """Return nearby OCR artifacts for diagnostics."""
    candidates = {"ocr_dirs": [], "ocr_json": [], "pages_dirs": [], "images_dirs": []}
    try:
        for p in company_dir.rglob("ocr"):
            if p.is_dir():
                candidates["ocr_dirs"].append(p)
        for j in company_dir.rglob("ocr_result.json"):
            candidates["ocr_json"].append(j)
        for p in company_dir.rglob("pages"):
            if p.is_dir():
                candidates["pages_dirs"].append(p)
        for p in company_dir.rglob("images"):
            if p.is_dir():
                candidates["images_dirs"].append(p)
    except Exception:
        pass
    return candidates


def ensure_ocr_for_company(company_dir: Path, data_dir: Path) -> Path | None:
    """
    Ensure company_dir/ocr exists. If not, try to locate OCR artifacts anywhere under
    the company_dir and copy them into company_dir/ocr. Returns the Path to the OCR
    directory that will be used (company_dir/ocr) or None if nothing found.
    """
    ocr_dir = company_dir / "ocr"
    # already present
    if ocr_dir.exists() and any(ocr_dir.iterdir()):
        return ocr_dir

    # 1) Prefer an existing 'ocr' folder anywhere inside company_dir
    for candidate in company_dir.rglob("ocr"):
        if candidate.is_dir():
            try:
                ocr_dir.mkdir(parents=True, exist_ok=True)
                # copy contents (images, pages, json) into company_dir/ocr
                for child in candidate.iterdir():
                    dst = ocr_dir / child.name
                    if child.is_dir():
                        shutil.copytree(child, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(child, dst)
                return ocr_dir
            except Exception:
                continue

    # 2) Look for any ocr_result.json somewhere under company_dir and materialize pages/
    for json_path in company_dir.rglob("ocr_result.json"):
        try:
            src = json_path.parent
            ocr_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(json_path, ocr_dir / "ocr_result.json")
            # copy sibling folders if present
            for name in ("pages", "images"):
                src_dir = src / name
                if src_dir.exists() and src_dir.is_dir():
                    dst = ocr_dir / name
                    shutil.copytree(src_dir, dst, dirs_exist_ok=True)
            # if no pages directory present, try to materialize pages from the JSON
            if not (ocr_dir / "pages").exists():
                try:
                    write_pages_from_ocr_json(company_dir, ocr_dir / "ocr_result.json")
                    # write_pages_from_ocr_json writes into company_dir/pages — copy into ocr/pages
                    generated = company_dir / "pages"
                    if generated.exists():
                        shutil.copytree(generated, ocr_dir / "pages", dirs_exist_ok=True)
                except Exception:
                    pass
            return ocr_dir
        except Exception:
            continue

    # 3) Look for any 'pages' folder under company_dir and copy into company_dir/ocr/pages
    for pages in company_dir.rglob("pages"):
        if pages.is_dir():
            try:
                ocr_dir.mkdir(parents=True, exist_ok=True)
                dst = ocr_dir / "pages"
                shutil.copytree(pages, dst, dirs_exist_ok=True)
                # also copy sibling images if present
                if (pages.parent / "images").exists():
                    shutil.copytree(pages.parent / "images", ocr_dir / "images", dirs_exist_ok=True)
                return ocr_dir
            except Exception:
                continue

    return None


def collect_ocr_text(company_dir: Path) -> str:
    """
    Improved recursive search for OCR files to handle nested structures
    like 'company_dir/Subfolder_pdf/pages/*.md'
    """
    texts = []
    seen_md_files = set()
    found_json = False

    # 1. Search for any 'pages' folder recursively inside company_dir
    # This handles the case where OCR is in 'company/Some_Document_pdf/pages/'
    for pages_dir in company_dir.rglob("pages"):
        if pages_dir.is_dir():
            # Get all .md files, sorted by name (page_0000.md, etc.)
            md_files = sorted(list(pages_dir.glob("*.md")))
            for md in md_files:
                if md.name not in seen_md_files:
                    try:
                        content = md.read_text(encoding="utf-8").strip()
                        if content:
                            # Use relative path as a header so LLM knows the source
                            rel_path = md.relative_to(company_dir)
                            texts.append(f"--- Document: {rel_path} ---\n{content}")
                            seen_md_files.add(md.name)
                    except Exception:
                        continue

    # 2. If no .md files found, fallback to searching for any 'ocr_result.json' recursively
    if not texts:
        for json_path in company_dir.rglob("ocr_result.json"):
            try:
                raw = load_json(json_path)
                if raw and "pages" in raw:
                    for page in raw["pages"]:
                        md_text = page.get("markdown", "").strip()
                        if md_text:
                            idx = page.get("index", 0)
                            texts.append(f"--- Document JSON Page {idx} ---\n{md_text}")
                    found_json = True
                    break # Usually one JSON is enough
            except Exception:
                continue

    return "\n\n".join(texts)


def get_ocr_text(company_dir: Path) -> str:
    """Consolidated helper to return combined text found in the directory."""
    return collect_ocr_text(company_dir)


def list_companies() -> list[str]:
    if not DATA_DIR.exists():
        return []
    return sorted([
        d.name for d in DATA_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".")
        and (d / "mcq_answers").exists()
    ])


def list_answer_files(company_dir: Path) -> list[Path]:
    ans_dir = company_dir / "mcq_answers"
    if not ans_dir.exists():
        return []
    return sorted(ans_dir.glob("*.json"), reverse=True)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS — OPENROUTER
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_models(api_key: str) -> list[dict]:
    try:
        r = requests.get(OPENROUTER_MODELS_URL,
                         headers={"Authorization": f"Bearer {api_key}"},
                         timeout=10)
        r.raise_for_status()
        return [{"id": m["id"], "name": m.get("name", m["id"])}
                for m in r.json().get("data", [])]
    except Exception:
        return [{"id": DEFAULT_MODEL, "name": DEFAULT_MODEL}]


def call_openrouter(messages: list[dict], model: str, api_key: str,
                    temperature: float = 0.1, max_tokens: int = 8000) -> str:
    if not api_key:
        raise ValueError("No OpenRouter API key.")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    for attempt in range(3):
        try:
            r = requests.post(OPENROUTER_API_URL, headers=headers,
                              json=payload, timeout=120)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# VERIFICATION PROMPT
# ══════════════════════════════════════════════════════════════════════════════

VERIFICATION_SYSTEM_PROMPT = """\
You are an expert ESG analyst and auditor. Your task is to verify MCQ answers against company document evidence (OCR-extracted text).

For EACH question, you must:
1. Search the OCR text for relevant evidence.
2. Determine if the selected answer is SUPPORTED, PARTIALLY SUPPORTED, CONTRADICTED, or NOT FOUND in the evidence.
3. Provide a confidence score (0-100) for the verification.
4. Extract a direct quote or relevant passage from the OCR as supporting evidence (max 200 chars).
5. Provide brief reasoning (1-2 sentences).

Return your response as a valid JSON array with this exact structure:
[
  {
    "id": "E01",
    "verification_status": "SUPPORTED" | "PARTIALLY_SUPPORTED" | "CONTRADICTED" | "NOT_FOUND",
    "confidence": 85,
    "evidence_quote": "direct quote from OCR text or empty string",
    "evidence_page": "page reference or empty string",
    "reasoning": "brief explanation of verification decision",
    "suggested_answer": "A" | "B" | "C" | "D" | null
  },
  ...
]

Return ONLY the JSON array. No preamble, no explanation outside the array.
"""


def build_verification_prompt(answers: list[dict], ocr_text: str, max_ocr_chars: int = 15000) -> str:
    # Truncate OCR to fit context
    ocr_snippet = ocr_text[:max_ocr_chars]
    if len(ocr_text) > max_ocr_chars:
        ocr_snippet += f"\n\n[... OCR text truncated at {max_ocr_chars} chars ...]"

    qa_block = []
    for a in answers:
        qa_block.append(
            f"ID: {a.get('id')}\n"
            f"Pillar: {a.get('pillar','')}\n"
            f"Question: {a.get('question','')}\n"
            f"Selected Answer: {a.get('selected','')} — {a.get('selected_text','')}\n"
        )

    return f"""
OCR DOCUMENT TEXT:
{ocr_snippet}

===

MCQ ANSWERS TO VERIFY ({len(answers)} questions):
{'---'.join(qa_block)}

Verify each answer against the OCR document text above. Return a JSON array as instructed.
""".strip()


def parse_verification_json(raw: str) -> list[dict] | None:
    """Extract and parse JSON array from LLM response."""
    # try direct parse
    try:
        data = json.loads(raw.strip())
        if isinstance(data, list):
            return data
    except Exception:
        pass
    # try extracting fenced block
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # try finding bare array
    m2 = re.search(r"\[.*\]", raw, re.S)
    if m2:
        try:
            return json.loads(m2.group(0))
        except Exception:
            pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
# SCORING
# ══════════════════════════════════════════════════════════════════════════════

STATUS_MULTIPLIER = {
    "SUPPORTED":           1.0,
    "PARTIALLY_SUPPORTED": 0.7,
    "NOT_FOUND":           0.5,   # answer accepted but unverified
    "CONTRADICTED":        0.0,
}


def compute_scores(answers: list[dict], verifications: list[dict]) -> pd.DataFrame:
    """Merge answers + verifications and compute scores."""
    ver_map = {v["id"]: v for v in verifications}
    rows = []
    for a in answers:
        qid = a.get("id", "")
        sel = a.get("selected", "")
        raw_score = CHOICE_SCORE.get(sel, 0)
        ver = ver_map.get(qid, {})
        status = ver.get("verification_status", "NOT_FOUND")
        multiplier = STATUS_MULTIPLIER.get(status, 0.5)
        final_score = round(raw_score * multiplier, 2)
        rows.append({
            "ID":                 qid,
            "Pillar":             a.get("pillar", ""),
            "Question":           a.get("question", "")[:80] + ("…" if len(a.get("question","")) > 80 else ""),
            "Selected":           sel,
            "Selected Text":      a.get("selected_text", ""),
            "Raw Score":          raw_score,
            "Max Score":          MAX_SCORE_PER_QUESTION,
            "Status":             status,
            "Confidence":         ver.get("confidence", 0),
            "Multiplier":         multiplier,
            "Final Score":        final_score,
            "Evidence Quote":     ver.get("evidence_quote", ""),
            "Evidence Page":      ver.get("evidence_page", ""),
            "Reasoning":          ver.get("reasoning", ""),
            "Suggested Answer":   ver.get("suggested_answer", ""),
        })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# UI HELPERS
# ══════════════════════════════════════════════════════════════════════════════

STATUS_COLORS = {
    "SUPPORTED":           "🟢",
    "PARTIALLY_SUPPORTED": "🟡",
    "NOT_FOUND":           "🔵",
    "CONTRADICTED":        "🔴",
}

PILLAR_COLORS = {
    "Environmental": "#2e7d32",
    "Social":        "#1565c0",
    "Governance":    "#6a1b9a",
}


def pillar_badge(pillar: str) -> str:
    color = PILLAR_COLORS.get(pillar, "#555")
    return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:8px;font-size:0.75rem">{pillar}</span>'


def score_badge(score: float, max_score: float) -> str:
    pct = score / max_score if max_score > 0 else 0
    color = "#2e7d32" if pct >= 0.8 else "#f57c00" if pct >= 0.5 else "#c62828"
    return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:8px;font-size:0.85rem">{score:.1f}/{max_score}</span>'


def render_pillar_summary(df: pd.DataFrame):
    st.subheader("📊 Pillar Score Summary")
    cols = st.columns(3)
    for idx, pillar in enumerate(["Environmental", "Social", "Governance"]):
        sub = df[df["Pillar"] == pillar]
        if sub.empty:
            continue
        total_final  = sub["Final Score"].sum()
        total_max    = sub["Max Score"].sum()
        total_raw    = sub["Raw Score"].sum()
        pct          = (total_final / total_max * 100) if total_max > 0 else 0
        n_supported  = (sub["Status"] == "SUPPORTED").sum()
        n_partial    = (sub["Status"] == "PARTIALLY_SUPPORTED").sum()
        n_contradict = (sub["Status"] == "CONTRADICTED").sum()
        n_notfound   = (sub["Status"] == "NOT_FOUND").sum()

        with cols[idx]:
            color = PILLAR_COLORS.get(pillar, "#555")
            st.markdown(
                f'<div style="border:2px solid {color};border-radius:10px;padding:16px;margin-bottom:8px">'
                f'<h4 style="color:{color};margin:0">{pillar}</h4>'
                f'<div style="font-size:2rem;font-weight:bold;color:{color}">{pct:.0f}%</div>'
                f'<div style="font-size:0.9rem;color:#555">{total_final:.1f} / {total_max} pts (verified)</div>'
                f'<div style="font-size:0.85rem;color:#777">{total_raw} / {total_max} pts (raw)</div>'
                f'<hr style="margin:8px 0">'
                f'<div style="font-size:0.8rem">'
                f'🟢 Supported: {n_supported} &nbsp;'
                f'🟡 Partial: {n_partial}<br>'
                f'🔵 Not Found: {n_notfound} &nbsp;'
                f'🔴 Contradicted: {n_contradict}'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True
            )


def render_overall_score(df: pd.DataFrame):
    total_final = df["Final Score"].sum()
    total_max   = df["Max Score"].sum()
    total_raw   = df["Raw Score"].sum()
    pct         = (total_final / total_max * 100) if total_max > 0 else 0

    color = "#2e7d32" if pct >= 70 else "#f57c00" if pct >= 40 else "#c62828"
    grade = "A" if pct >= 80 else "B" if pct >= 65 else "C" if pct >= 50 else "D" if pct >= 35 else "F"

    st.markdown(
        f'<div style="background:linear-gradient(135deg,{color}22,{color}44);'
        f'border:3px solid {color};border-radius:16px;padding:24px;text-align:center;margin-bottom:24px">'
        f'<h2 style="margin:0;color:{color}">Overall ESG Score</h2>'
        f'<div style="font-size:4rem;font-weight:900;color:{color};line-height:1.1">'
        f'{pct:.1f}% <span style="font-size:2rem">({grade})</span></div>'
        f'<div style="font-size:1.1rem;color:#555">'
        f'Verified: {total_final:.1f} / {total_max} pts &nbsp;|&nbsp; Raw: {total_raw} / {total_max} pts</div>'
        f'<div style="font-size:0.85rem;color:#777;margin-top:8px">'
        f'Score = Raw choice score × Verification multiplier '
        f'(Supported=1.0 · Partial=0.7 · Not Found=0.5 · Contradicted=0.0)</div>'
        f'</div>',
        unsafe_allow_html=True
    )


def render_question_detail(row: pd.Series, expanded: bool = False):
    status = row["Status"]
    icon   = STATUS_COLORS.get(status, "⚪")
    color  = {"SUPPORTED": "#e8f5e9", "PARTIALLY_SUPPORTED": "#fffde7",
               "CONTRADICTED": "#ffebee", "NOT_FOUND": "#e3f2fd"}.get(status, "#fafafa")

    with st.container():
        st.markdown(
            f'<div style="background:{color};border-radius:8px;padding:12px 16px;margin-bottom:8px">'
            f'<b>{row["ID"]}</b> {pillar_badge(row["Pillar"])} &nbsp; '
            f'{icon} <b>{status}</b> &nbsp; '
            f'Confidence: {row["Confidence"]}% &nbsp; '
            f'{score_badge(row["Final Score"], row["Max Score"])}'
            f'<br><span style="color:#333">{row["Question"]}</span>'
            f'<br><b>Selected:</b> {row["Selected"]} — {row["Selected Text"]}'
            f'</div>',
            unsafe_allow_html=True
        )
        if expanded:
            c1, c2 = st.columns([2, 1])
            with c1:
                st.markdown(f"**Reasoning:** {row['Reasoning']}")
                if row["Evidence Quote"]:
                    st.markdown(f"**Evidence:** _{row['Evidence Quote']}_")
                if row["Evidence Page"]:
                    st.caption(f"Source: {row['Evidence Page']}")
            with c2:
                if row["Suggested Answer"] and row["Suggested Answer"] != row["Selected"]:
                    st.warning(f"💡 Suggested answer: **{row['Suggested Answer']}**")
                st.metric("Raw Score", f"{row['Raw Score']}/{row['Max Score']}")
                st.metric("Verified Score", f"{row['Final Score']}/{row['Max Score']}")


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════

_DEFAULTS = {
    "api_key":        os.getenv("OPENROUTER_API_KEY", ""),
    "model_id":       DEFAULT_MODEL,
    "verification":   None,   # list[dict] from LLM
    "score_df":       None,   # pd.DataFrame
    "raw_llm_reply":  "",
    "ocr_text":       "",
    "answer_data":    None,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.header("⚙️ Settings")
    api_key_input = st.text_input(
        "OpenRouter API Key",
        value=st.session_state.api_key,
        type="password",
        help="Required for LLM verification"
    )
    if api_key_input:
        st.session_state.api_key = api_key_input

    if st.session_state.api_key:
        with st.spinner("Loading models…"):
            models = fetch_models(st.session_state.api_key)
        model_ids = [m["id"] for m in models]
        default_idx = next(
            (i for i, m in enumerate(model_ids) if DEFAULT_MODEL in m), 0
        )
        selected_model = st.selectbox(
            "Model",
            options=model_ids,
            index=default_idx,
            format_func=lambda x: x.split("/")[-1]
        )
        st.session_state.model_id = selected_model
    else:
        st.warning("Enter API key to load models.")

    st.divider()
    st.markdown("""
**Score Legend:**
| Status | Multiplier |
|--------|-----------|
| 🟢 Supported | 1.0× |
| 🟡 Partial | 0.7× |
| 🔵 Not Found | 0.5× |
| 🔴 Contradicted | 0.0× |

**Choice Score:**
| Choice | Points |
|--------|--------|
| A | 3 |
| B | 2 |
| C | 1 |
| D | 0 |
""")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PAGE
# ══════════════════════════════════════════════════════════════════════════════

st.title("🔍 MCQ LLM Verification & Scoring")
st.caption("Verify MCQ answers against OCR-extracted company documents using an LLM.")

# ── Step 1: Company & file selection ──────────────────────────────────────────
st.header("Step 1 — Select Company & Answer File")

companies = list_companies()
if not companies:
    st.error("No companies with MCQ answers found in the data directory.")
    st.stop()

col1, col2 = st.columns(2)
with col1:
    company_name = st.selectbox("Company", options=companies)

company_dir  = DATA_DIR / company_name
answer_files = list_answer_files(company_dir)

if not answer_files:
    st.warning(f"No MCQ answer files found for **{company_name}**.")
    st.stop()

with col2:
    selected_file = st.selectbox(
        "MCQ Answer File",
        options=answer_files,
        format_func=lambda p: p.name
    )

# Load answer file
answer_data = load_json(selected_file)
if not answer_data:
    st.error(f"Could not load {selected_file.name}")
    st.stop()

st.session_state.answer_data = answer_data
answers: list[dict] = answer_data.get("answers", [])

# Display answer file metadata
with st.expander("📄 Answer file metadata", expanded=False):
    st.json({
        "company":     answer_data.get("company"),
        "timestamp":   answer_data.get("timestamp"),
        "mode":        answer_data.get("mode"),
        "n_answers":   len(answers),
        "source_mode": answer_data.get("source_mode", ""),
    })

# ── Step 2: Load & preview OCR ────────────────────────────────────────────────
st.header("Step 2 — OCR Document Text")

with st.spinner("Locating / Loading OCR text…"):
    # try to auto-fix by copying a found OCR bundle into company_dir/ocr/
    ensured_path = ensure_ocr_for_company(company_dir, DATA_DIR)
    # if ensure_ocr_for_company returned a specific ocr dir, use it; else fall back to recursive search
    search_base = ensured_path if ensured_path is not None else company_dir
    ocr_text = get_ocr_text(search_base)
    st.session_state.ocr_text = ocr_text
    ocr_source = ensured_path

if not ocr_text.strip():
    # provide actionable diagnostics
    candidates = list_ocr_candidates(company_dir)
    msg_lines = [
        f"⚠️ No OCR text found for **{company_name}**. Verification will proceed but all answers will return NOT_FOUND.",
        "",
        "I looked for common OCR artifacts under the company folder. Found:"
    ]
    if candidates["ocr_dirs"]:
        msg_lines.append(f"- ocr folders: {', '.join(str(p.relative_to(DATA_DIR)) for p in candidates['ocr_dirs'])}")
    if candidates["ocr_json"]:
        msg_lines.append(f"- ocr_result.json files: {', '.join(str(p.relative_to(DATA_DIR)) for p in candidates['ocr_json'])}")
    if candidates["pages_dirs"]:
        msg_lines.append(f"- pages/ folders: {', '.join(str(p.relative_to(DATA_DIR)) for p in candidates['pages_dirs'])}")
    if candidates["images_dirs"]:
        msg_lines.append(f"- images/ folders: {', '.join(str(p.relative_to(DATA_DIR)) for p in candidates['images_dirs'])}")

    msg_lines.append("")
    msg_lines.append("Tip: If you see OCR bundles in the list above, you can copy them into the company `ocr/` folder and rerun the verification. The app attempts to auto-copy common structures but will show the candidates above if it couldn't.")
    st.warning("\n".join(msg_lines))
    ocr_available = False
else:
    ocr_available = True
    # show a clearer source path
    try:
        src_display = (ocr_source.relative_to(DATA_DIR) if ocr_source and DATA_DIR in ocr_source.parents else (ocr_source or company_dir))
    except Exception:
        src_display = ocr_source or company_dir
    st.success(f"✅ OCR text loaded — {len(ocr_text):,} characters from `{src_display}`")

with st.expander("👁️ Preview OCR text (first 3000 chars)", expanded=False):
    st.code(ocr_text[:3000] + ("…" if len(ocr_text) > 3000 else ""), language="markdown")

# ── Step 3: Run verification ───────────────────────────────────────────────────
st.header("Step 3 — LLM Verification")

col_run, col_clear = st.columns([2, 1])
with col_run:
    run_btn = st.button(
        "🚀 Run LLM Verification",
        type="primary",
        disabled=not st.session_state.api_key,
        help="Sends MCQ answers + OCR text to LLM for verification"
    )
with col_clear:
    if st.button("🗑️ Clear Results"):
        st.session_state.verification  = None
        st.session_state.score_df      = None
        st.session_state.raw_llm_reply = ""
        st.rerun()

if not st.session_state.api_key:
    st.info("Enter your OpenRouter API key in the sidebar to enable verification.")

if run_btn:
    if not answers:
        st.error("No answers found in the selected file.")
    else:
        prompt_user = build_verification_prompt(answers, ocr_text, max_ocr_chars=14000)
        messages = [
            {"role": "system", "content": VERIFICATION_SYSTEM_PROMPT},
            {"role": "user",   "content": prompt_user},
        ]

        progress = st.progress(0, text="Sending to LLM…")
        t0 = time.time()

        try:
            with st.spinner(f"Verifying {len(answers)} answers with **{st.session_state.model_id}**…"):
                raw_reply = call_openrouter(
                    messages=messages,
                    model=st.session_state.model_id,
                    api_key=st.session_state.api_key,
                    temperature=0.1,
                    max_tokens=10000,
                )
            elapsed = time.time() - t0
            progress.progress(80, text="Parsing response…")

            verifications = parse_verification_json(raw_reply)
            if verifications is None:
                st.error("❌ Could not parse JSON from LLM. See raw reply below.")
                st.code(raw_reply)
            else:
                # Merge any missing IDs with NOT_FOUND
                ver_ids = {v["id"] for v in verifications}
                for a in answers:
                    if a["id"] not in ver_ids:
                        verifications.append({
                            "id":                  a["id"],
                            "verification_status": "NOT_FOUND",
                            "confidence":          0,
                            "evidence_quote":      "",
                            "evidence_page":       "",
                            "reasoning":           "Not returned by LLM.",
                            "suggested_answer":    None,
                        })

                score_df = compute_scores(answers, verifications)
                st.session_state.verification  = verifications
                st.session_state.score_df      = score_df
                st.session_state.raw_llm_reply = raw_reply

                # Save verification result
                out_dir  = company_dir / "mcq_answers"
                out_dir.mkdir(parents=True, exist_ok=True)
                ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
                out_path = out_dir / f"{ts}_verification.json"
                result_payload = {
                    "company":         company_name,
                    "source_file":     selected_file.name,
                    "timestamp":       datetime.utcnow().isoformat() + "Z",
                    "model":           st.session_state.model_id,
                    "total_final_score":  float(score_df["Final Score"].sum()),
                    "total_max_score":    int(score_df["Max Score"].sum()),
                    "total_raw_score":    int(score_df["Raw Score"].sum()),
                    "pct_verified":    round(score_df["Final Score"].sum() / score_df["Max Score"].sum() * 100, 2),
                    "verifications":   verifications,
                    "scores":          score_df.to_dict(orient="records"),
                }
                out_path.write_text(
                    json.dumps(result_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                progress.progress(100, text=f"Done in {elapsed:.1f}s")
                st.success(f"✅ Verification complete in {elapsed:.1f}s — saved to `{out_path.name}`")

        except Exception as e:
            st.error(f"LLM call failed: {e}")
            progress.empty()

# ── Step 4: Results ────────────────────────────────────────────────────────────
if st.session_state.score_df is not None:
    st.divider()
    st.header("Step 4 — Results")

    df: pd.DataFrame = st.session_state.score_df

    # Overall score banner
    render_overall_score(df)

    # Pillar summary
    render_pillar_summary(df)

    st.divider()

    # ── Tabs: Detail view, Table, Download ────────────────────────────────────
    tab_detail, tab_table, tab_raw, tab_download = st.tabs([
        "📋 Question Detail", "📊 Score Table", "🤖 Raw LLM Reply", "⬇️ Download"
    ])

    with tab_detail:
        pillar_filter = st.radio(
            "Filter by pillar",
            ["All", "Environmental", "Social", "Governance"],
            horizontal=True,
        )
        status_filter = st.multiselect(
            "Filter by verification status",
            ["SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_FOUND", "CONTRADICTED"],
            default=["SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_FOUND", "CONTRADICTED"],
        )

        filtered = df.copy()
        if pillar_filter != "All":
            filtered = filtered[filtered["Pillar"] == pillar_filter]
        if status_filter:
            filtered = filtered[filtered["Status"].isin(status_filter)]

        st.caption(f"Showing {len(filtered)} of {len(df)} questions")

        expand_all = st.checkbox("Expand all questions", value=False)
        for _, row in filtered.iterrows():
            render_question_detail(row, expanded=expand_all)

    with tab_table:
        display_cols = [
            "ID", "Pillar", "Question", "Selected", "Selected Text",
            "Raw Score", "Status", "Confidence", "Multiplier",
            "Final Score", "Max Score", "Reasoning"
        ]
        st.dataframe(
            df[display_cols].style.apply(
                lambda row: [
                    "background-color:#e8f5e9" if row["Status"] == "SUPPORTED"
                    else "background-color:#fffde7" if row["Status"] == "PARTIALLY_SUPPORTED"
                    else "background-color:#ffebee" if row["Status"] == "CONTRADICTED"
                    else "background-color:#e3f2fd"
                    for _ in row
                ],
                axis=1
            ),
            use_container_width=True,
            height=600,
        )
        # Pillar summary table
        st.subheader("Pillar Totals")
        pillar_summary = df.groupby("Pillar").agg(
            Questions=("ID", "count"),
            Raw_Score=("Raw Score", "sum"),
            Final_Score=("Final Score", "sum"),
            Max_Score=("Max Score", "sum"),
            Avg_Confidence=("Confidence", "mean"),
        ).reset_index()
        pillar_summary["Score_%"] = (
            pillar_summary["Final_Score"] / pillar_summary["Max_Score"] * 100
        ).round(1)
        st.dataframe(pillar_summary, use_container_width=True)

    with tab_raw:
        st.caption("Raw JSON response from LLM")
        st.code(st.session_state.raw_llm_reply, language="json")

    with tab_download:
        st.subheader("Download Results")

        # JSON download
        result_json = {
            "company":          company_name,
            "source_file":      selected_file.name,
            "timestamp":        datetime.utcnow().isoformat() + "Z",
            "model":            st.session_state.model_id,
            "total_final_score": float(df["Final Score"].sum()),
            "total_max_score":  int(df["Max Score"].sum()),
            "pct_verified":     round(df["Final Score"].sum() / df["Max Score"].sum() * 100, 2),
            "scores":           df.to_dict(orient="records"),
            "verifications":    st.session_state.verification,
        }
        st.download_button(
            "📥 Download Full Verification JSON",
            data=json.dumps(result_json, ensure_ascii=False, indent=2),
            file_name=f"{company_name}_verification_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.json",
            mime="application/json",
        )

        # CSV download
        st.download_button(
            "📥 Download Score Table CSV",
            data=df.to_csv(index=False),
            file_name=f"{company_name}_scores_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.csv",
            mime="text/csv",
        )

    # ── Post-processing section (for OCR cleaning) ───────────────────────────────
    st.divider()
    st.header("🔧 OCR Post-processing")

    if st.button("🧹 Clean OCR Text & Restructure"):
        with st.spinner("Cleaning OCR text…"):
            try:
                # Step 1: Write pages from existing ocr_result.json if present
                for company_name in list_companies():
                    company_dir = DATA_DIR / company_name
                    ocr_json = company_dir / "ocr" / "ocr_result.json"
                    if ocr_json.exists():
                        write_pages_from_ocr_json(company_dir, ocr_json)

                # Step 2: Clean all pages in parallel
                def clean_task(company_name: str):
                    company_dir = DATA_DIR / company_name
                    clean_pages_folder(company_dir)

                from concurrent.futures import ThreadPoolExecutor, as_completed
                with ThreadPoolExecutor(max_workers=8) as executor:
                    futures = {executor.submit(clean_task, cn): cn for cn in list_companies()}
                    for future in as_completed(futures):
                        cn = futures[future]
                        try:
                            future.result()
                        except Exception as e:
                            st.warning(f"Error cleaning {cn}: {e}")

                st.success("✅ OCR text cleaning complete.")
            except Exception as e:
                st.error(f"Cleaning failed: {e}")

    st.markdown("""
**Note:** The cleaning process will:
- Write individual page markdown files from existing `ocr_result.json` (if present).
- Clean markdown in all `pages/*.md` files: fix formatting, remove empty lines, etc.
- This will restructure the OCR data. Ensure you have backups if needed.
""")
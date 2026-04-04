"""
────────────────────────────────────────────────────────────────────────────────
MCQ LLM Verification & Scoring Page
────────────────────────────────────────────────────────────────────────────────
"""

import html
import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MCQ LLM Verification",
    page_icon="🔍",
    layout="wide",
)

# ── Paths & env ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
load_dotenv(BASE_DIR / ".env")

OPENROUTER_API_URL    = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_MODELS_URL = os.getenv("OPENROUTER_MODELS_URL", "https://openrouter.ai/api/v1/models")
DEFAULT_MODEL         = "meta-llama/llama-3.1-8b-instruct:free"

CHOICE_SCORE = {"A": 3, "B": 2, "C": 1, "D": 0, "": 0}
MAX_SCORE_PER_QUESTION = 3

# ══════════════════════════════════════════════════════════════════════════════
# VERIFICATION SYSTEM PROMPT  ← must be defined before UI
# ══════════════════════════════════════════════════════════════════════════════

VERIFICATION_SYSTEM_PROMPT = """
You are an objective verifier comparing multiple-choice answers against an OCR-extracted document.
Return a JSON array where each element corresponds to one input question ID and has the following keys:
- id: (string) the question ID from the input
- verification_status: one of ["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"]
- confidence: numeric 0-100 estimating certainty of the verification
- evidence_quote: short quote (<=250 chars) from the OCR that justifies the verdict, or "" if none
- evidence_page: page identifier (e.g., "page_0003.md" or "Document JSON Page 2") where evidence was found, or "" if none
- reasoning: plain-text explanation of how you reached the decision
- suggested_answer: if the original selected answer seems wrong, suggest one of "A","B","C","D", or null

Important:
- Output only a single JSON array (or a fenced ```json block containing the array). Avoid extra commentary.
- Be conservative: when evidence is partial, prefer PARTIALLY_SUPPORTED with a moderate confidence.
- Use NOT_FOUND when no supporting text is present, not when contradictory evidence exists.
"""

# ══════════════════════════════════════════════════════════════════════════════
# LLM / API HELPERS  ← defined BEFORE any UI code
# ══════════════════════════════════════════════════════════════════════════════

def _get_api_key() -> str:
    # 1. Session state (user typed it in)
    if st.session_state.get("api_key", "").strip():
        return st.session_state["api_key"].strip()
    # 2. Env / .env / config.settings fallback
    try:
        from config.settings import settings
        for attr in ("OPENROUTER_API_KEY", "openrouter_api_key", "api_key"):
            val = getattr(settings, attr, None)
            if val and str(val).strip():
                return str(val).strip()
    except Exception:
        pass
    return os.getenv("OPENROUTER_API_KEY", "")


def fetch_models(api_key: str) -> list[dict]:
    """
    Fetch available models from OpenRouter; fall back to a minimal list on error.
    Mirrors the Chatbot's model discovery (more robust headers & parsing).
    """
    def _fallback():
        return [{"id": DEFAULT_MODEL, "name": DEFAULT_MODEL}]

    if not api_key:
        return _fallback()
    try:
        resp = requests.get(
            OPENROUTER_MODELS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer":  "https://pear-edtech.app",
                "X-Title":       "Pear EdTech Chatbot",
            },
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json().get("data", []) or []
        models = []
        for m in raw:
            mid = m.get("id", "")
            name = m.get("name", mid)
            if not mid:
                continue
            # try to capture useful metadata if present
            ctx = m.get("context_length", 0) if isinstance(m, dict) else 0
            pricing = m.get("pricing", {}) if isinstance(m, dict) else {}
            models.append({"id": mid, "name": name, "ctx": ctx, "pricing": pricing})
        return models or _fallback()
    except Exception:
        return _fallback()


def call_openrouter(messages: list[dict], model: str, api_key: str,
                    temperature: float = 0.2, max_tokens: int = 2000) -> str:
    """
    Send a chat-style request to the OpenRouter API using the stronger headers used by the Chatbot.
    Returns assistant content string (or an error string on failure).
    """
    effective_key = api_key or _get_api_key()
    if not effective_key:
        raise RuntimeError("Missing OpenRouter API key.")

    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    headers = {
        "Authorization": f"Bearer {effective_key}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://pear-edtech.app",
        "X-Title":       "Pear EdTech Chatbot",
    }
    try:
        r = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=120)
        r.raise_for_status()
        j = r.json()
        # typical OpenRouter shape: {"choices":[{"message":{"role":"assistant","content":"..."}}], ...}
        choices = j.get("choices", [])
        if choices and isinstance(choices, list):
            msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            return msg.get("content", "") or str(j)
        # fallback: some implementations return choices[0]["text"]
        if choices and isinstance(choices[0], dict) and "text" in choices[0]:
            return choices[0]["text"]
        return str(j)
    except Exception as e:
        return f"[LLM Error: {e}]"

# ══════════════════════════════════════════════════════════════════════════════
# DATA HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_json(p: Path, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_table_line(line: str) -> bool:
    return line.strip().startswith("|") or bool(re.match(r"^\s*\|.*\|\s*$", line))


def clean_markdown(md: str) -> str:
    md = html.unescape(md)
    md = re.sub(r"^\s*!\[[^\]]*\]\([^\)]+\)\s*$\n?", "", md, flags=re.M)
    md = re.sub(r"data:image\/[a-zA-Z]+;base64,[A-Za-z0-9+/=\s]+", "", md)
    md = re.sub(r"(\w)-\n(\w)", r"\1\2", md)
    lines = md.splitlines()
    out_lines: List[str] = []
    inside_table = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if is_table_line(line):
            inside_table = True
            out_lines.append(line.rstrip())
            continue
        else:
            if inside_table and stripped == "":
                inside_table = False
        if re.match(r"^(#{1,6}\s)|^(\s*[-*+]\s)|^>\s|^---\s*$|^\s*\d+\.\s", line):
            out_lines.append(line.rstrip())
            continue
        if stripped == "":
            out_lines.append("")
            continue
        next_line = lines[i + 1] if i + 1 < len(lines) else ""
        if (next_line.strip() == ""
                or re.match(r"^(#{1,6}\s)|^(\s*[-*+]\s)|^>\s|^\s*\d+\.\s", next_line)
                or is_table_line(next_line)):
            out_lines.append(line.rstrip())
        else:
            out_lines.append(line.rstrip() + " ")
    joined = "\n".join(out_lines)
    joined = re.sub(r"[ \t]{2,}", " ", joined)
    joined = re.sub(r"\s+([,.;:!?])", r"\1", joined)
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
    for p in pages:
        p["markdown"] = clean_markdown(p.get("markdown", ""))
    save_json(ocr_json_path, data)


def clean_pages_folder(doc_dir: Path):
    pages_dir = doc_dir / "pages"
    if not pages_dir.exists():
        return
    for md in sorted(pages_dir.glob("*.md")):
        txt = md.read_text(encoding="utf-8")
        md.write_text(clean_markdown(txt), encoding="utf-8")

# ══════════════════════════════════════════════════════════════════════════════
# OCR DISCOVERY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def list_ocr_candidates(company_dir: Path) -> dict:
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


def _has_ocr_content(p: Path) -> bool:
    try:
        return any(p.rglob("*.md")) or (p / "ocr_result.json").exists() or any(p.rglob("ocr_result.json"))
    except Exception:
        return False


def ensure_ocr_for_company(company_dir: Path, data_dir: Path) -> Path | None:
    """
    Find a usable OCR source for company_dir.
    Priority:
      1. company_dir/ocr (if it has content)
      2. Any nested ocr/ folder inside company_dir
      3. Any ocr_result.json inside company_dir
      4. Any nested pages/ inside company_dir
      5. GLOBAL FALLBACK: search all of data_dir for ocr_result.json
         (handles the case where OCR lives in a sibling dataset folder)
    """
    ocr_dir = company_dir / "ocr"

    # 1) Canonical location
    if ocr_dir.exists() and _has_ocr_content(ocr_dir):
        return ocr_dir

    # 2) Nested ocr/ folders inside company_dir
    nested_ocrs = sorted(
        [p for p in company_dir.rglob("ocr") if p.is_dir() and p.resolve() != ocr_dir.resolve()],
        key=lambda p: len(p.parts), reverse=True
    )
    for cand in nested_ocrs:
        if not _has_ocr_content(cand):
            continue
        try:
            ocr_dir.mkdir(parents=True, exist_ok=True)
            for child in cand.iterdir():
                dst = ocr_dir / child.name
                if child.is_dir():
                    shutil.copytree(child, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, dst)
            if _has_ocr_content(ocr_dir):
                return ocr_dir
        except Exception:
            return cand

    # 3) ocr_result.json anywhere inside company_dir
    for j in company_dir.rglob("ocr_result.json"):
        parent = j.parent
        if _has_ocr_content(parent):
            try:
                ocr_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(j, ocr_dir / "ocr_result.json")
                for name in ("pages", "images"):
                    src = parent / name
                    if src.exists() and src.is_dir():
                        shutil.copytree(src, ocr_dir / name, dirs_exist_ok=True)
                if _has_ocr_content(ocr_dir):
                    return ocr_dir
            except Exception:
                return parent

    # 4) Nested pages/ inside company_dir
    for pages in sorted(company_dir.rglob("pages"), key=lambda p: len(p.parts), reverse=True):
        if pages.is_dir() and any(pages.glob("*.md")):
            try:
                ocr_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(pages, ocr_dir / "pages", dirs_exist_ok=True)
                if _has_ocr_content(ocr_dir):
                    return ocr_dir
            except Exception:
                return pages

    # 5) ── GLOBAL FALLBACK ──────────────────────────────────────────────────
    #    Search ALL of data_dir for any ocr_result.json.
    #    This resolves the case where OCR lives in:
    #      data/thesis_dataset/CSSA ESG support Document 2023_pdf/ocr_result.json
    #    but selected company is:
    #      data/Testing 2/
    try:
        for j in sorted(data_dir.rglob("ocr_result.json")):
            # skip if this json is already inside company_dir (already checked above)
            try:
                j.relative_to(company_dir)
                continue  # inside company_dir → already handled
            except ValueError:
                pass  # outside company_dir → good candidate

            parent = j.parent
            if not _has_ocr_content(parent):
                continue
            try:
                ocr_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(j, ocr_dir / "ocr_result.json")
                for name in ("pages", "images"):
                    src = parent / name
                    if src.exists() and src.is_dir():
                        shutil.copytree(src, ocr_dir / name, dirs_exist_ok=True)
                if _has_ocr_content(ocr_dir):
                    return ocr_dir
            except Exception:
                # can't copy → use in-place
                return parent
    except Exception:
        pass

    return None


def collect_ocr_text(source_dir: Path, company_base: Path | None = None) -> str:
    texts = []
    seen_paths: set = set()

    # Try ocr_result.json first
    json_path = source_dir / "ocr_result.json"
    if json_path.exists():
        data = load_json(json_path)
        if data and isinstance(data.get("pages", []), list):
            for page in data["pages"]:
                idx = page.get("index", 0)
                md = page.get("markdown", "").strip()
                if md:
                    texts.append(f"--- Document JSON Page {idx} ---\n{clean_markdown(md)}")
            if texts:
                return "\n\n".join(texts)

    # Try pages/ directory
    pages_dir = source_dir if source_dir.name == "pages" else source_dir / "pages"
    if pages_dir.exists() and pages_dir.is_dir():
        for md_file in sorted(pages_dir.glob("*.md")):
            if md_file.resolve() in seen_paths:
                continue
            try:
                content = md_file.read_text(encoding="utf-8").strip()
                if content:
                    try:
                        rel = md_file.relative_to(company_base) if company_base else md_file.name
                    except ValueError:
                        rel = md_file.name
                    texts.append(f"--- Document: {rel} ---\n{content}")
                    seen_paths.add(md_file.resolve())
            except Exception:
                continue

    # Broad fallback
    if not texts:
        for pd2 in source_dir.rglob("pages"):
            if pd2.is_dir():
                for md_file in sorted(pd2.glob("*.md")):
                    if md_file.resolve() in seen_paths:
                        continue
                    try:
                        content = md_file.read_text(encoding="utf-8").strip()
                        if content:
                            texts.append(f"--- Document: {md_file} ---\n{content}")
                            seen_paths.add(md_file.resolve())
                    except Exception:
                        continue

    # Final fallback: any ocr_result.json recursively
    if not texts:
        for j in source_dir.rglob("ocr_result.json"):
            try:
                raw = load_json(j)
                if raw and "pages" in raw:
                    for page in raw["pages"]:
                        md = page.get("markdown", "").strip()
                        if md:
                            texts.append(f"--- Document JSON Page {page.get('index', 0)} ---\n{clean_markdown(md)}")
                    if texts:
                        break
            except Exception:
                continue

    return "\n\n".join(texts)


def get_ocr_text(company_dir: Path) -> tuple[str, Path | None]:
    try:
        ocr_source = ensure_ocr_for_company(company_dir, DATA_DIR)
        if ocr_source:
            text = collect_ocr_text(ocr_source, company_base=company_dir)
            return text or "", ocr_source
    except Exception:
        pass
    return "", None

# ══════════════════════════════════════════════════════════════════════════════
# FILESYSTEM UI HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def list_companies() -> list[str]:
    try:
        return sorted([p.name for p in DATA_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")])
    except Exception:
        return []


def list_answer_files(company_dir: Path) -> list[Path]:
    candidate_dir = company_dir / "mcq_answers"
    if candidate_dir.exists() and candidate_dir.is_dir():
        return sorted(candidate_dir.glob("*.json"))
    return sorted(company_dir.glob("*.json"))

# ══════════════════════════════════════════════════════════════════════════════
# CHUNKING + RETRIEVAL
# ══════════════════════════════════════════════════════════════════════════════

def chunk_text(text: str, size: int = 1000, overlap: int = 200) -> list[str]:
    if not text:
        return []
    chunks = []
    i = 0
    L = len(text)
    while i < L:
        chunks.append(text[i: min(i + size, L)])
        i += size - overlap
    return chunks


def retrieve_relevant_chunks(query: str, chunks: list[str], top_k: int = 8) -> list[str]:
    if not chunks:
        return []
    q_tokens = set(re.findall(r"\w+", query.lower()))
    scored = []
    for idx, c in enumerate(chunks):
        c_tokens = set(re.findall(r"\w+", c.lower()))
        scored.append((len(q_tokens & c_tokens), idx, c))
    scored.sort(key=lambda x: (x[0], -x[1]), reverse=True)
    top_sorted = sorted(scored[:top_k], key=lambda x: x[1])
    return [t[2] for t in top_sorted]


def build_verification_prompt(answers: list[dict], ocr_text: str, max_ocr_chars: int = 15000) -> str:
    if not ocr_text:
        ocr_snippet = "[NO OCR TEXT PROVIDED]"
    elif len(ocr_text) <= max_ocr_chars:
        ocr_snippet = ocr_text
    else:
        qs = " ".join([a.get("question", "") + " " + a.get("selected_text", "") for a in answers])
        chunks = chunk_text(ocr_text, size=1200, overlap=250)
        top_chunks = retrieve_relevant_chunks(qs, chunks, top_k=12)
        ocr_snippet = "\n\n---\n\n".join(top_chunks)
        if len(ocr_snippet) > max_ocr_chars:
            ocr_snippet = ocr_snippet[:max_ocr_chars]
        ocr_snippet += f"\n\n[... OCR retrieved + truncated; original length: {len(ocr_text)} chars ...]"

    qa_block = []
    for a in answers:
        qa_block.append(
            f"ID: {a.get('id')}\n"
            f"Pillar: {a.get('pillar', '')}\n"
            f"Question: {a.get('question', '')}\n"
            f"Selected Answer: {a.get('selected', '')} — {a.get('selected_text', '')}\n"
        )

    return (
        f"OCR DOCUMENT TEXT (retrieved snippets):\n{ocr_snippet}\n\n===\n\n"
        f"MCQ ANSWERS TO VERIFY ({len(answers)} questions):\n{'---'.join(qa_block)}\n\n"
        f"Verify each answer against the OCR document text above. Return a JSON array as instructed."
    )


def parse_verification_json(raw: str) -> list[dict] | None:
    try:
        data = json.loads(raw.strip())
        if isinstance(data, list):
            return data
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
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
    "NOT_FOUND":           0.5,
    "CONTRADICTED":        0.0,
}


def compute_scores(answers: list[dict], verifications: list[dict]) -> pd.DataFrame:
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
            "ID":               qid,
            "Pillar":           a.get("pillar", ""),
            "Question":         a.get("question", "")[:80] + ("…" if len(a.get("question", "")) > 80 else ""),
            "Selected":         sel,
            "Selected Text":    a.get("selected_text", ""),
            "Raw Score":        raw_score,
            "Max Score":        MAX_SCORE_PER_QUESTION,
            "Status":           status,
            "Confidence":       ver.get("confidence", 0),
            "Multiplier":       multiplier,
            "Final Score":      final_score,
            "Evidence Quote":   ver.get("evidence_quote", ""),
            "Evidence Page":    ver.get("evidence_page", ""),
            "Reasoning":        ver.get("reasoning", ""),
            "Suggested Answer": ver.get("suggested_answer", ""),
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
        color = PILLAR_COLORS.get(pillar, "#555")
        with cols[idx]:
            st.markdown(
                f'<div style="border:2px solid {color};border-radius:10px;padding:16px;margin-bottom:8px">'
                f'<h4 style="color:{color};margin:0">{pillar}</h4>'
                f'<div style="font-size:2rem;font-weight:bold;color:{color}">{pct:.0f}%</div>'
                f'<div style="font-size:0.9rem;color:#555">{total_final:.1f} / {total_max} pts (verified)</div>'
                f'<div style="font-size:0.85rem;color:#777">{total_raw} / {total_max} pts (raw)</div>'
                f'<hr style="margin:8px 0">'
                f'<div style="font-size:0.8rem">'
                f'🟢 {n_supported} &nbsp;🟡 {n_partial}<br>🔵 {n_notfound} &nbsp;🔴 {n_contradict}'
                f'</div></div>',
                unsafe_allow_html=True,
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
        f'</div>',
        unsafe_allow_html=True,
    )


def render_question_detail(row: pd.Series, expanded: bool = False):
    status = row["Status"]
    icon   = STATUS_COLORS.get(status, "⚪")
    color  = {
        "SUPPORTED": "#e8f5e9", "PARTIALLY_SUPPORTED": "#fffde7",
        "CONTRADICTED": "#ffebee", "NOT_FOUND": "#e3f2fd",
    }.get(status, "#fafafa")
    with st.container():
        st.markdown(
            f'<div style="background:{color};border-radius:8px;padding:12px 16px;margin-bottom:8px">'
            f'<b>{row["ID"]}</b> {pillar_badge(row["Pillar"])} &nbsp;'
            f'{icon} <b>{status}</b> &nbsp; Confidence: {row["Confidence"]}% &nbsp;'
            f'{score_badge(row["Final Score"], row["Max Score"])}'
            f'<br><span style="color:#333">{row["Question"]}</span>'
            f'<br><b>Selected:</b> {row["Selected"]} — {row["Selected Text"]}'
            f'</div>',
            unsafe_allow_html=True,
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
                    st.warning(f"💡 Suggested: **{row['Suggested Answer']}**")
                st.metric("Raw Score",      f"{row['Raw Score']}/{row['Max Score']}")
                st.metric("Verified Score", f"{row['Final Score']}/{row['Max Score']}")

# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════

_DEFAULTS = {
    "api_key":       os.getenv("OPENROUTER_API_KEY", ""),
    "model_id":      DEFAULT_MODEL,
    "verification":  None,
    "score_df":      None,
    "raw_llm_reply": "",
    "ocr_text":      "",
    "answer_data":   None,
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
        "OpenRouter API Key", value=st.session_state.api_key,
        type="password", help="Required for LLM verification",
    )
    if api_key_input:
        st.session_state.api_key = api_key_input

    if st.session_state.api_key:
        with st.spinner("Loading models…"):
            models = fetch_models(st.session_state.api_key)
        model_ids = [m["id"] for m in models]
        default_idx = next((i for i, mid in enumerate(model_ids) if DEFAULT_MODEL in mid), 0)
        selected_model = st.selectbox(
            "Model", options=model_ids, index=default_idx,
            format_func=lambda x: x.split("/")[-1],
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

# ── Step 1 ─────────────────────────────────────────────────────────────────────
st.header("Step 1 — Select Company & Answer File")

companies = list_companies()
if not companies:
    st.error("No company folders found in the data directory.")
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
        "MCQ Answer File", options=answer_files,
        format_func=lambda p: p.name,
    )

answer_data = load_json(selected_file)
if not answer_data:
    st.error(f"Could not load {selected_file.name}")
    st.stop()

st.session_state.answer_data = answer_data
answers: list[dict] = answer_data.get("answers", [])

with st.expander("📄 Answer file metadata", expanded=False):
    st.json({
        "company":     answer_data.get("company"),
        "timestamp":   answer_data.get("timestamp"),
        "mode":        answer_data.get("mode"),
        "n_answers":   len(answers),
        "source_mode": answer_data.get("source_mode", ""),
    })

# ── Step 2 ─────────────────────────────────────────────────────────────────────
st.header("Step 2 — OCR Document Text")

with st.spinner("Locating / loading OCR text…"):
    # Auto-detected OCR for selected company (keeps previous behavior)
    auto_ocr_text, auto_detected_source = get_ocr_text(company_dir)
    st.session_state.ocr_text = auto_ocr_text or ""
    auto_source = auto_detected_source

    # Build list of all OCR bundles under DATA_DIR for manual selection
    all_ocr_jsons = sorted(DATA_DIR.rglob("ocr_result.json"))
    ocr_display_options = [str(p.relative_to(DATA_DIR)) for p in all_ocr_jsons]

    # Offer multi-select: either Auto-detect OR one/more explicit OCR bundles
    st.subheader("Choose OCR source(s)")
    st.caption("Pick one or more OCR bundles from the dataset. Select 'Auto-detect' to use the app's automatic discovery for the selected company.")
    ocr_multiselect = st.multiselect(
        "Select OCR bundles (multiple allowed)",
        options=["Auto-detect"] + ocr_display_options,
        default=["Auto-detect"] if auto_detected_source else [],
        help="Selecting multiple bundles will merge their text in the order chosen."
    )

    # If user explicitly picked external bundles (and did NOT pick Auto-detect),
    # load and merge them. Otherwise keep auto-detect result.
    combined_texts = []
    selected_sources = []

    if ocr_multiselect and "Auto-detect" not in ocr_multiselect:
        for choice in ocr_multiselect:
            sel_path = DATA_DIR / Path(choice)
            if sel_path.exists():
                txt = collect_ocr_text(sel_path.parent, company_base=company_dir)
                if txt:
                    header = f"--- OCR: {str(sel_path.parent.relative_to(DATA_DIR))} ---"
                    combined_texts.append(f"{header}\n{txt}")
                    selected_sources.append(sel_path.parent)
    else:
        # use auto-detect if present
        if auto_ocr_text:
            combined_texts.append(f"--- Auto-detected: {str(auto_source.relative_to(DATA_DIR)) if auto_source else company_name} ---\n{auto_ocr_text}")
            if auto_source:
                selected_sources.append(auto_source)

    # Finalize session OCR text and source(s)
    final_ocr_text = "\n\n".join(combined_texts).strip()
    st.session_state.ocr_text = final_ocr_text or ""
    ocr_source = selected_sources if selected_sources else (auto_source if auto_source else None)

if not st.session_state.ocr_text.strip():
    candidates = list_ocr_candidates(company_dir)
    msg_lines = [
        f"⚠️ No OCR text found for **{company_name}**. All answers will return NOT_FOUND.",
        "",
        "Artifacts found under company folder:",
    ]
    if candidates["ocr_dirs"]:
        msg_lines.append("- ocr folders: " + ", ".join(str(p.relative_to(DATA_DIR)) for p in candidates["ocr_dirs"]))
    if candidates["ocr_json"]:
        msg_lines.append("- ocr_result.json: " + ", ".join(str(p.relative_to(DATA_DIR)) for p in candidates["ocr_json"]))
    if candidates["pages_dirs"]:
        msg_lines.append("- pages/ folders: " + ", ".join(str(p.relative_to(DATA_DIR)) for p in candidates["pages_dirs"]))
    msg_lines.append("")
    msg_lines.append("Tip: Use the multiselect above to pick one or more OCR bundles from other dataset folders.")
    st.warning("\n".join(msg_lines))
    ocr_available = False
else:
    ocr_available = True
    # show all detected/selected sources in success message
    try:
        if isinstance(ocr_source, list):
            src_display = ", ".join(str(p.relative_to(DATA_DIR)) for p in ocr_source)
        else:
            src_display = ocr_source.relative_to(DATA_DIR) if ocr_source else company_dir
    except Exception:
        src_display = ocr_source or company_dir
    st.success(f"✅ OCR loaded — {len(st.session_state.ocr_text):,} chars from `{src_display}`")

with st.expander("👁️ Preview OCR text (first 3 000 chars)", expanded=False):
    preview = st.session_state.ocr_text
    st.code(preview[:3000] + ("…" if len(preview) > 3000 else ""), language="markdown")

# ── Step 3 ─────────────────────────────────────────────────────────────────────
st.header("Step 3 — LLM Verification")

col_run, col_clear = st.columns([2, 1])
with col_run:
    run_btn = st.button(
        "🚀 Run LLM Verification", type="primary",
        disabled=not st.session_state.api_key,
        help="Sends MCQ answers + OCR text to LLM for verification",
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
        # prepare output path early so we can always write a result file
        out_dir  = company_dir / "mcq_answers"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        out_path = out_dir / f"{ts}_verification.json"

        prompt_user = build_verification_prompt(answers, st.session_state.ocr_text, max_ocr_chars=14000)
        messages = [
            {"role": "system", "content": VERIFICATION_SYSTEM_PROMPT},
            {"role": "user",   "content": prompt_user},
        ]
        progress = st.progress(0, text="Sending to LLM…")
        t0 = time.time()
        raw_reply = None
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

            # If parsing failed, still create a NOT_FOUND fallback for every question and save raw reply
            if verifications is None:
                st.warning("⚠️ LLM returned a non-JSON or unparsable response. Saving raw reply and marking answers as NOT_FOUND.")
                verifications = []
                for a in answers:
                    verifications.append({
                        "id": a["id"],
                        "verification_status": "NOT_FOUND",
                        "confidence": 0,
                        "evidence_quote": "",
                        "evidence_page": "",
                        "reasoning": "LLM response unparsable; raw reply saved.",
                        "suggested_answer": None,
                    })

                # save failure payload with raw reply for debugging
                result_payload = {
                    "company": company_name,
                    "source_file": selected_file.name,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "model": st.session_state.model_id,
                    "status": "parse_error",
                    "error": "LLM response could not be parsed as JSON",
                    "raw_llm_reply": raw_reply,
                    "verifications": verifications,
                }
                out_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                st.session_state.verification  = verifications
                st.session_state.score_df      = compute_scores(answers, verifications)
                st.session_state.raw_llm_reply = raw_reply or ""
                progress.progress(100, text=f"Done in {elapsed:.1f}s (parse error saved)")
                st.error("❌ Could not parse JSON from LLM. Raw reply saved to disk.")
            else:
                # ensure every question has a verification entry
                ver_ids = {v.get("id") for v in verifications}
                for a in answers:
                    if a["id"] not in ver_ids:
                        verifications.append({
                            "id": a["id"], "verification_status": "NOT_FOUND",
                            "confidence": 0, "evidence_quote": "",
                            "evidence_page": "", "reasoning": "Not returned by LLM.",
                            "suggested_answer": None,
                        })
                score_df = compute_scores(answers, verifications)
                st.session_state.verification  = verifications
                st.session_state.score_df      = score_df
                st.session_state.raw_llm_reply = raw_reply or ""

                result_payload = {
                    "company": company_name, "source_file": selected_file.name,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "model": st.session_state.model_id,
                    "status": "ok",
                    "total_final_score": float(score_df["Final Score"].sum()),
                    "total_max_score":   int(score_df["Max Score"].sum()),
                    "total_raw_score":   int(score_df["Raw Score"].sum()),
                    "pct_verified": round(score_df["Final Score"].sum() / score_df["Max Score"].sum() * 100, 2) if score_df["Max Score"].sum() else 0,
                    "verifications": verifications,
                    "scores": score_df.to_dict(orient="records"),
                    "raw_llm_reply": raw_reply,
                }
                out_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                elapsed = time.time() - t0
                progress.progress(100, text=f"Done in {elapsed:.1f}s")
                st.success(f"✅ Verification complete in {elapsed:.1f}s — saved to `{out_path.name}`")
        except Exception as e:
            # Always save an error file with as much context as possible
            err_info = {
                "company": company_name,
                "source_file": selected_file.name,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "model": st.session_state.model_id,
                "status": "error",
                "error": str(e),
                "raw_llm_reply": raw_reply,
            }
            try:
                out_path.write_text(json.dumps(err_info, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                # best-effort write; ignore if disk write fails
                pass
            st.error(f"LLM call failed: {e}")
            progress.empty()

# ── Step 4 ─────────────────────────────────────────────────────────────────────
if st.session_state.score_df is not None:
    st.divider()
    st.header("Step 4 — Results")
    df: pd.DataFrame = st.session_state.score_df
    render_overall_score(df)
    render_pillar_summary(df)
    st.divider()

    tab_detail, tab_table, tab_raw, tab_download = st.tabs([
        "📋 Question Detail", "📊 Score Table", "🤖 Raw LLM Reply", "⬇️ Download",
    ])

    with tab_detail:
        pillar_filter = st.radio("Filter by pillar", ["All", "Environmental", "Social", "Governance"], horizontal=True)
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
            "Raw Score", "Status", "Confidence", "Multiplier", "Final Score", "Max Score", "Reasoning",
        ]
        st.dataframe(df[display_cols], use_container_width=True, height=600)
        st.subheader("Pillar Totals")
        pillar_summary = df.groupby("Pillar").agg(
            Questions=("ID", "count"),
            Raw_Score=("Raw Score", "sum"),
            Final_Score=("Final Score", "sum"),
            Max_Score=("Max Score", "sum"),
            Avg_Confidence=("Confidence", "mean"),
        ).reset_index()
        pillar_summary["Score_%"] = (pillar_summary["Final_Score"] / pillar_summary["Max_Score"] * 100).round(1)
        st.dataframe(pillar_summary, use_container_width=True)

    with tab_raw:
        st.caption("Raw JSON response from LLM")
        st.code(st.session_state.raw_llm_reply, language="json")

    with tab_download:
        st.subheader("Download Results")
        result_json = {
            "company": company_name, "source_file": selected_file.name,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "model": st.session_state.model_id,
            "total_final_score": float(df["Final Score"].sum()),
            "total_max_score":   int(df["Max Score"].sum()),
            "pct_verified": round(df["Final Score"].sum() / df["Max Score"].sum() * 100, 2),
            "scores": df.to_dict(orient="records"),
            "verifications": st.session_state.verification,
        }
        st.download_button(
            "📥 Download Full Verification JSON",
            data=json.dumps(result_json, ensure_ascii=False, indent=2),
            file_name=f"{company_name}_verification_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.json",
            mime="application/json",
        )
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
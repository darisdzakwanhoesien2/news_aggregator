"""
────────────────────────────────────────────────────────────────────────────────
MCQ LLM Verification & Scoring Page  (v2 – stable rewrite)
────────────────────────────────────────────────────────────────────────────────
"""

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

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MCQ LLM Verification",
    page_icon="🔍",
    layout="wide",
)

# ── Paths & env ────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).resolve().parents[1]
DATA_DIR      = BASE_DIR / "data"
USER_DATA_DIR = BASE_DIR / "user_data"
LOG_DIR       = BASE_DIR / "logs"
TMP_DIR       = DATA_DIR / "thesis_pdf"
OUT_DIR       = DATA_DIR / "thesis_dataset"

for _d in (DATA_DIR, USER_DATA_DIR, LOG_DIR, TMP_DIR, OUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

OPENROUTER_API_URL    = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_MODELS_URL = os.getenv("OPENROUTER_MODELS_URL", "https://openrouter.ai/api/v1/models")
DEFAULT_MODEL         = "meta-llama/llama-3.1-8b-instruct:free"

CHOICE_SCORE           = {"A": 3, "B": 2, "C": 1, "D": 0, "": 0}
MAX_SCORE_PER_QUESTION = 3

ESG_MCQ_JSON = DATA_DIR / "esg_mcq.json"


def _load_esg_mcq() -> list[dict]:
    if ESG_MCQ_JSON.exists():
        try:
            data = json.loads(ESG_MCQ_JSON.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return []


ESG_MCQ: list[dict] = _load_esg_mcq()

# ══════════════════════════════════════════════════════════════════════════════
# VERIFICATION SYSTEM PROMPT
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
# DATA HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_json(p: Path, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_name(name: str) -> str:
    if not name:
        return "file"
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def is_table_line(line: str) -> bool:
    return line.strip().startswith("|") or bool(re.match(r"^\s*\|.*\|\s*$", line))


def clean_markdown(md: str) -> str:
    md = html.unescape(md)
    md = re.sub(r"^\s*!\[[^\]]*\]\([^\)]+\)\s*$\n?", "", md, flags=re.M)
    md = re.sub(r"data:image\/[a-zA-Z]+;base64,[A-Za-z0-9+/=\s]+", "", md)
    md = re.sub(r"(\w)-\n(\w)", r"\1\2", md)
    lines        = md.splitlines()
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
        if (
            next_line.strip() == ""
            or re.match(r"^(#{1,6}\s)|^(\s*[-*+]\s)|^>\s|^\s*\d+\.\s", next_line)
            or is_table_line(next_line)
        ):
            out_lines.append(line.rstrip())
        else:
            out_lines.append(line.rstrip() + " ")
    joined = "\n".join(out_lines)
    joined = re.sub(r"[ \t]{2,}", " ", joined)
    joined = re.sub(r"\s+([,.;:!?])", r"\1", joined)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip() + "\n"

# ══════════════════════════════════════════════════════════════════════════════
# OCR HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def collect_ocr_text(source_dir: Path, company_base: Path | None = None) -> str:
    texts: list[str] = []
    seen_paths: set  = set()

    # 1. ocr_result.json
    json_path = source_dir / "ocr_result.json"
    if json_path.exists():
        data = load_json(json_path)
        if data and isinstance(data.get("pages", []), list):
            for page in data["pages"]:
                idx = page.get("index", 0)
                md  = page.get("markdown", "").strip()
                if md:
                    texts.append(f"--- Document JSON Page {idx} ---\n{clean_markdown(md)}")
            if texts:
                return "\n\n".join(texts)

    # 2. pages/*.md
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

    # 3. Broad fallback: nested pages/ dirs
    if not texts:
        for sub_pages in source_dir.rglob("pages"):
            if sub_pages.is_dir():
                for md_file in sorted(sub_pages.glob("*.md")):
                    if md_file.resolve() in seen_paths:
                        continue
                    try:
                        content = md_file.read_text(encoding="utf-8").strip()
                        if content:
                            texts.append(f"--- Document: {md_file} ---\n{content}")
                            seen_paths.add(md_file.resolve())
                    except Exception:
                        continue

    # 4. Final fallback: any ocr_result.json recursively
    if not texts:
        for j in source_dir.rglob("ocr_result.json"):
            try:
                raw = load_json(j)
                if raw and "pages" in raw:
                    for page in raw["pages"]:
                        md = page.get("markdown", "").strip()
                        if md:
                            texts.append(
                                f"--- Document JSON Page {page.get('index', 0)} ---\n{clean_markdown(md)}"
                            )
                    if texts:
                        break
            except Exception:
                continue

    return "\n\n".join(texts)


def _has_ocr_content(p: Path) -> bool:
    try:
        return any(p.rglob("*.md")) or (p / "ocr_result.json").exists() or any(p.rglob("ocr_result.json"))
    except Exception:
        return False

# ══════════════════════════════════════════════════════════════════════════════
# SESSION FILESYSTEM HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_user_dir(username: str) -> Path:
    return USER_DATA_DIR / username


def get_sessions_dir(username: str) -> Path:
    return get_user_dir(username) / "sessions"


def create_new_session(username: str) -> tuple[str, Path]:
    ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    sess_dir = get_sessions_dir(username) / ts
    for sub in ("inputs", "documents", "processing", "outputs", "logs"):
        (sess_dir / sub).mkdir(parents=True, exist_ok=True)
    meta = {
        "session_id":  ts,
        "username":    username,
        "created_at":  datetime.utcnow().isoformat() + "Z",
        "status":      "created",
        "doc_count":   0,
        "company":     "",
        "answer_mode": "",
    }
    (sess_dir / "metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return ts, sess_dir


def list_user_sessions(username: str) -> list[dict]:
    """Return list of session metadata dicts, newest first."""
    sessions_dir = get_sessions_dir(username)
    if not sessions_dir.exists():
        return []
    result = []
    for p in sorted(sessions_dir.iterdir(), reverse=True):
        if not p.is_dir():
            continue
        meta_file = p / "metadata.json"
        if meta_file.exists():
            try:
                m = json.loads(meta_file.read_text(encoding="utf-8"))
                result.append(m)
            except Exception:
                result.append({"session_id": p.name, "created_at": p.name})
        else:
            result.append({"session_id": p.name, "created_at": p.name})
    return result


def get_session_path(username: str, session_id: str) -> Path:
    return get_sessions_dir(username) / session_id


def update_session_meta(sess_dir: Path, updates: dict):
    meta_file = sess_dir / "metadata.json"
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    except Exception:
        meta = {}
    meta.update(updates)
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def add_document_to_session(sess_dir: Path, file_bytes: bytes, filename: str) -> Path:
    """
    Save an uploaded file into the next available doc_XXX slot.
    Layout:
      session/documents/doc_001/original/<filename>
      session/documents/doc_001/ocr/
      session/documents/doc_001/metadata.json
    """
    docs_dir = sess_dir / "documents"
    existing = sorted([d for d in docs_dir.iterdir() if d.is_dir() and d.name.startswith("doc_")])
    next_idx  = len(existing) + 1
    doc_dir   = docs_dir / f"doc_{next_idx:03d}"
    orig_dir  = doc_dir / "original"
    orig_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "ocr").mkdir(parents=True, exist_ok=True)

    safe_fname = safe_name(filename)
    out_path   = orig_dir / safe_fname
    out_path.write_bytes(file_bytes)

    doc_meta = {
        "doc_id":        f"doc_{next_idx:03d}",
        "original_name": filename,
        "filename":      safe_fname,
        "size":          len(file_bytes),
        "uploaded_at":   datetime.utcnow().isoformat() + "Z",
        "ocr_status":    "pending",
    }
    (doc_dir / "metadata.json").write_text(
        json.dumps(doc_meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return doc_dir


def list_session_documents(sess_dir: Path) -> list[dict]:
    """Return list of document metadata dicts for a session."""
    docs_dir = sess_dir / "documents"
    if not docs_dir.exists():
        return []
    result = []
    for d in sorted(docs_dir.iterdir()):
        if not d.is_dir() or not d.name.startswith("doc_"):
            continue
        mf = d / "metadata.json"
        if mf.exists():
            try:
                m = json.loads(mf.read_text(encoding="utf-8"))
                m["_path"] = str(d)
                result.append(m)
            except Exception:
                result.append({"doc_id": d.name, "_path": str(d)})
    return result


def get_combined_ocr_text(sess_dir: Path) -> str:
    """
    Merge OCR text from all doc_XXX/ocr/ folders within a session.
    Uses processing/combined_ocr.txt as a non-empty cache.
    """
    combined_cache = sess_dir / "processing" / "combined_ocr.txt"

    if combined_cache.exists():
        try:
            cached = combined_cache.read_text(encoding="utf-8").strip()
            if cached:
                return cached
            combined_cache.unlink(missing_ok=True)
        except Exception:
            combined_cache.unlink(missing_ok=True)

    texts = []
    for doc in list_session_documents(sess_dir):
        doc_path = Path(doc["_path"])
        ocr_dir  = doc_path / "ocr"
        if not ocr_dir.exists():
            continue

        t = collect_ocr_text(ocr_dir)

        # Strategy 2: bundle subdirs (e.g. ocr/my_doc_pdf/)
        if not t:
            for sub in sorted(ocr_dir.iterdir()):
                if sub.is_dir():
                    t = collect_ocr_text(sub)
                    if t:
                        break

        # Strategy 3: rglob ocr_result.json
        if not t:
            for ocr_json in ocr_dir.rglob("ocr_result.json"):
                try:
                    data = load_json(ocr_json)
                    if data and isinstance(data.get("pages", []), list):
                        page_texts = []
                        for page in data["pages"]:
                            md = page.get("markdown", "").strip()
                            if md:
                                page_texts.append(
                                    f"--- Document JSON Page {page.get('index', 0)} ---\n{clean_markdown(md)}"
                                )
                        if page_texts:
                            t = "\n\n".join(page_texts)
                            break
                except Exception:
                    continue

        # Strategy 4: rglob *.md
        if not t:
            md_files = sorted(ocr_dir.rglob("*.md"))
            if md_files:
                page_texts = []
                for md_file in md_files:
                    try:
                        content = md_file.read_text(encoding="utf-8").strip()
                        if content:
                            page_texts.append(f"--- {md_file.name} ---\n{content}")
                    except Exception:
                        continue
                t = "\n\n".join(page_texts)

        if t:
            texts.append(f"=== Document: {doc.get('original_name', doc['doc_id'])} ===\n{t}")

    merged = "\n\n".join(texts)
    if merged:
        try:
            combined_cache.parent.mkdir(parents=True, exist_ok=True)
            combined_cache.write_text(merged, encoding="utf-8")
        except Exception:
            pass
    return merged

# ══════════════════════════════════════════════════════════════════════════════
# LLM / API HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_api_key() -> str:
    if st.session_state.get("api_key", "").strip():
        return st.session_state["api_key"].strip()
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
        raw    = resp.json().get("data", []) or []
        models = []
        for m in raw:
            mid  = m.get("id", "")
            name = m.get("name", mid)
            if not mid:
                continue
            models.append({"id": mid, "name": name})
        return models or _fallback()
    except Exception:
        return _fallback()


def call_openrouter(
    messages: list[dict],
    model: str,
    api_key: str,
    temperature: float = 0.2,
    max_tokens: int = 10000,
) -> str:
    """
    Stable OpenRouter call. Returns assistant content string or error string.
    """
    effective_key = api_key or _get_api_key()
    if not effective_key:
        raise RuntimeError("Missing OpenRouter API key.")

    payload = {
        "model":       model,
        "messages":    messages,
        "temperature": float(temperature),
        "max_tokens":  int(max_tokens),
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

        choices = j.get("choices", [])
        if choices and isinstance(choices, list):
            msg     = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            content = msg.get("content", "") if isinstance(msg, dict) else ""
            if content:
                return content
        # older shape
        if choices and isinstance(choices[0], dict) and "text" in choices[0]:
            return choices[0]["text"]
        return str(j)

    except Exception as e:
        return f"[LLM Error: {e}]"

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
    scored   = []
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
        qs         = " ".join([a.get("question", "") + " " + a.get("selected_text", "") for a in answers])
        chunks     = chunk_text(ocr_text, size=1200, overlap=250)
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
    rows    = []
    for a in answers:
        qid       = a.get("id", "")
        sel       = a.get("selected", "")
        raw_score = CHOICE_SCORE.get(sel, 0)
        ver       = ver_map.get(qid, {})
        status    = ver.get("verification_status", "NOT_FOUND")
        multiplier   = STATUS_MULTIPLIER.get(status, 0.5)
        final_score  = round(raw_score * multiplier, 2)
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
    return (
        f'<span style="background:{color};color:white;padding:2px 8px;'
        f'border-radius:8px;font-size:0.75rem">{pillar}</span>'
    )


def score_badge(score: float, max_score: float) -> str:
    pct   = score / max_score if max_score > 0 else 0
    color = "#2e7d32" if pct >= 0.8 else "#f57c00" if pct >= 0.5 else "#c62828"
    return (
        f'<span style="background:{color};color:white;padding:2px 8px;'
        f'border-radius:8px;font-size:0.85rem">{score:.1f}/{max_score}</span>'
    )


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
        color        = PILLAR_COLORS.get(pillar, "#555")
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
        "SUPPORTED":           "#e8f5e9",
        "PARTIALLY_SUPPORTED": "#fffde7",
        "CONTRADICTED":        "#ffebee",
        "NOT_FOUND":           "#e3f2fd",
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
        model_ids   = [m["id"] for m in models]
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
    # Auto-detect: look for combined_ocr.txt in any session, or direct company ocr/
    auto_ocr_text = ""
    auto_source   = None

    # Try company_dir/ocr first
    company_ocr = company_dir / "ocr"
    if company_ocr.exists() and _has_ocr_content(company_ocr):
        auto_ocr_text = collect_ocr_text(company_ocr, company_base=company_dir)
        auto_source   = company_ocr

    # Build list of all OCR bundles under DATA_DIR for manual override
    all_ocr_jsons      = sorted(DATA_DIR.rglob("ocr_result.json"))
    ocr_display_options = [str(p.relative_to(DATA_DIR)) for p in all_ocr_jsons]

    st.subheader("Choose OCR source(s)")
    st.caption("Select one or more OCR bundles, or 'Auto-detect' to use the company folder's OCR.")
    ocr_multiselect = st.multiselect(
        "Select OCR bundles (multiple allowed)",
        options=["Auto-detect"] + ocr_display_options,
        default=["Auto-detect"] if auto_source else [],
    )

    combined_texts: list[str] = []
    selected_sources: list[Path] = []

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
        if auto_ocr_text:
            try:
                src_label = str(auto_source.relative_to(DATA_DIR)) if auto_source else company_name
            except Exception:
                src_label = company_name
            combined_texts.append(f"--- Auto-detected: {src_label} ---\n{auto_ocr_text}")
            if auto_source:
                selected_sources.append(auto_source)

    final_ocr_text = "\n\n".join(combined_texts).strip()
    st.session_state.ocr_text = final_ocr_text
    ocr_source = selected_sources if selected_sources else ([auto_source] if auto_source else [])

if not st.session_state.ocr_text.strip():
    st.warning(
        f"⚠️ No OCR text found for **{company_name}**. All answers will return NOT_FOUND.\n\n"
        "Tip: Use the multiselect above to pick one or more OCR bundles from dataset folders."
    )
    ocr_available = False
else:
    ocr_available = True
    try:
        src_display = ", ".join(str(p.relative_to(DATA_DIR)) for p in ocr_source)
    except Exception:
        src_display = company_name
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
        out_dir  = company_dir / "mcq_answers"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        out_path = out_dir / f"{ts}_verification.json"

        prompt_user = build_verification_prompt(answers, st.session_state.ocr_text, max_ocr_chars=14000)
        messages = [
            {"role": "system", "content": VERIFICATION_SYSTEM_PROMPT},
            {"role": "user",   "content": prompt_user},
        ]
        progress  = st.progress(0, text="Sending to LLM…")
        t0        = time.time()
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

            if verifications is None:
                st.warning("⚠️ LLM returned a non-JSON response. Saving raw reply; marking all as NOT_FOUND.")
                verifications = [
                    {
                        "id": a["id"],
                        "verification_status": "NOT_FOUND",
                        "confidence":    0,
                        "evidence_quote": "",
                        "evidence_page":  "",
                        "reasoning":     "LLM response unparsable; raw reply saved.",
                        "suggested_answer": None,
                    }
                    for a in answers
                ]
                result_payload = {
                    "company":       company_name,
                    "source_file":   selected_file.name,
                    "timestamp":     datetime.utcnow().isoformat() + "Z",
                    "model":         st.session_state.model_id,
                    "status":        "parse_error",
                    "error":         "LLM response could not be parsed as JSON",
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
                # Ensure every question has a verification entry
                ver_ids = {v.get("id") for v in verifications}
                for a in answers:
                    if a["id"] not in ver_ids:
                        verifications.append({
                            "id": a["id"], "verification_status": "NOT_FOUND",
                            "confidence": 0, "evidence_quote": "", "evidence_page": "",
                            "reasoning": "Not returned by LLM.", "suggested_answer": None,
                        })
                score_df = compute_scores(answers, verifications)
                st.session_state.verification  = verifications
                st.session_state.score_df      = score_df
                st.session_state.raw_llm_reply = raw_reply or ""

                result_payload = {
                    "company":           company_name,
                    "source_file":       selected_file.name,
                    "timestamp":         datetime.utcnow().isoformat() + "Z",
                    "model":             st.session_state.model_id,
                    "status":            "ok",
                    "total_final_score": float(score_df["Final Score"].sum()),
                    "total_max_score":   int(score_df["Max Score"].sum()),
                    "total_raw_score":   int(score_df["Raw Score"].sum()),
                    "pct_verified":      round(
                        score_df["Final Score"].sum() / score_df["Max Score"].sum() * 100, 2
                    ) if score_df["Max Score"].sum() else 0,
                    "verifications":     verifications,
                    "scores":            score_df.to_dict(orient="records"),
                    "raw_llm_reply":     raw_reply,
                }
                out_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                elapsed = time.time() - t0
                progress.progress(100, text=f"Done in {elapsed:.1f}s")
                st.success(f"✅ Verification complete in {elapsed:.1f}s — saved to `{out_path.name}`")

        except Exception as e:
            err_info = {
                "company":       company_name,
                "source_file":   selected_file.name,
                "timestamp":     datetime.utcnow().isoformat() + "Z",
                "model":         st.session_state.model_id,
                "status":        "error",
                "error":         str(e),
                "raw_llm_reply": raw_reply,
            }
            try:
                out_path.write_text(json.dumps(err_info, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
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
        pillar_filter = st.radio(
            "Filter by pillar", ["All", "Environmental", "Social", "Governance"], horizontal=True
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
        pillar_summary["Score_%"] = (
            pillar_summary["Final_Score"] / pillar_summary["Max_Score"] * 100
        ).round(1)
        st.dataframe(pillar_summary, use_container_width=True)

    with tab_raw:
        st.caption("Raw JSON response from LLM")
        st.code(st.session_state.raw_llm_reply, language="json")

    with tab_download:
        st.subheader("Download Results")
        result_json = {
            "company":           company_name,
            "source_file":       selected_file.name,
            "timestamp":         datetime.utcnow().isoformat() + "Z",
            "model":             st.session_state.model_id,
            "total_final_score": float(df["Final Score"].sum()),
            "total_max_score":   int(df["Max Score"].sum()),
            "pct_verified":      round(df["Final Score"].sum() / df["Max Score"].sum() * 100, 2),
            "scores":            df.to_dict(orient="records"),
            "verifications":     st.session_state.verification,
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

# """
# ────────────────────────────────────────────────────────────────────────────────
# MCQ LLM Verification & Scoring Page  (v2 – stable rewrite)
# ────────────────────────────────────────────────────────────────────────────────
# """

# import html
# import json
# import os
# import re
# import time
# from datetime import datetime
# from pathlib import Path
# from typing import List

# import base64
# import pandas as pd
# import requests
# import streamlit as st
# from dotenv import load_dotenv

# # ── Page config ────────────────────────────────────────────────────────────────
# st.set_page_config(
#     page_title="MCQ LLM Verification",
#     page_icon="🔍",
#     layout="wide",
# )

# # ── Paths & env ────────────────────────────────────────────────────────────────
# BASE_DIR      = Path(__file__).resolve().parents[1]
# DATA_DIR      = BASE_DIR / "data"
# USER_DATA_DIR = BASE_DIR / "user_data"
# LOG_DIR       = BASE_DIR / "logs"
# TMP_DIR       = DATA_DIR / "thesis_pdf"
# OUT_DIR       = DATA_DIR / "thesis_dataset"

# for _d in (DATA_DIR, USER_DATA_DIR, LOG_DIR, TMP_DIR, OUT_DIR):
#     _d.mkdir(parents=True, exist_ok=True)

# load_dotenv(BASE_DIR / ".env")

# OPENROUTER_API_URL    = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")
# OPENROUTER_MODELS_URL = os.getenv("OPENROUTER_MODELS_URL", "https://openrouter.ai/api/v1/models")
# DEFAULT_MODEL         = "meta-llama/llama-3.1-8b-instruct:free"

# MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
# MISTRAL_BASE    = "https://api.mistral.ai/v1"
# MISTRAL_HEADERS = {"Authorization": f"Bearer {MISTRAL_API_KEY}"} if MISTRAL_API_KEY else {}

# CHOICE_SCORE           = {"A": 3, "B": 2, "C": 1, "D": 0, "": 0}
# MAX_SCORE_PER_QUESTION = 3

# ESG_MCQ_JSON = DATA_DIR / "esg_mcq.json"


# def _load_esg_mcq() -> list[dict]:
#     if ESG_MCQ_JSON.exists():
#         try:
#             data = json.loads(ESG_MCQ_JSON.read_text(encoding="utf-8"))
#             if isinstance(data, list) and data:
#                 return data
#         except Exception:
#             pass
#     return []


# ESG_MCQ: list[dict] = _load_esg_mcq()

# # ══════════════════════════════════════════════════════════════════════════════
# # SESSION FILESYSTEM HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def get_user_dir(username: str) -> Path:
#     return USER_DATA_DIR / username


# def get_sessions_dir(username: str) -> Path:
#     return get_user_dir(username) / "sessions"


# def create_new_session(username: str) -> tuple[str, Path]:
#     ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
#     sess_dir = get_sessions_dir(username) / ts
#     for sub in ("inputs", "documents", "processing", "outputs", "logs"):
#         (sess_dir / sub).mkdir(parents=True, exist_ok=True)

#     meta = {
#         "session_id":  ts,
#         "username":    username,
#         "created_at":  datetime.utcnow().isoformat() + "Z",
#         "status":      "created",
#         "doc_count":   0,
#         "company":     "",
#         "answer_mode": "",
#     }
#     (sess_dir / "metadata.json").write_text(
#         json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return ts, sess_dir


# def list_user_sessions(username: str) -> list[dict]:
#     """Return list of session metadata dicts, newest first."""
#     sessions_dir = get_sessions_dir(username)
#     if not sessions_dir.exists():
#         return []
#     result = []
#     for p in sorted(sessions_dir.iterdir(), reverse=True):
#         if not p.is_dir():
#             continue
#         meta_file = p / "metadata.json"
#         if meta_file.exists():
#             try:
#                 m = json.loads(meta_file.read_text(encoding="utf-8"))
#                 result.append(m)
#             except Exception:
#                 result.append({"session_id": p.name, "created_at": p.name})
#         else:
#             result.append({"session_id": p.name, "created_at": p.name})
#     return result


# def get_session_path(username: str, session_id: str) -> Path:
#     return get_sessions_dir(username) / session_id


# def update_session_meta(sess_dir: Path, updates: dict):
#     meta_file = sess_dir / "metadata.json"
#     try:
#         meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
#     except Exception:
#         meta = {}
#     meta.update(updates)
#     meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# def add_document_to_session(sess_dir: Path, file_bytes: bytes, filename: str) -> Path:
#     """
#     Save an uploaded file into the next available doc_XXX slot.
#     Returns the doc directory.
#     Layout:
#       session/documents/doc_001/original/<filename>
#       session/documents/doc_001/ocr/        (populated after OCR)
#       session/documents/doc_001/metadata.json
#     """
#     docs_dir = sess_dir / "documents"
#     existing = sorted([d for d in docs_dir.iterdir() if d.is_dir() and d.name.startswith("doc_")])
#     next_idx  = len(existing) + 1
#     doc_dir   = docs_dir / f"doc_{next_idx:03d}"
#     orig_dir  = doc_dir / "original"
#     orig_dir.mkdir(parents=True, exist_ok=True)
#     (doc_dir / "ocr").mkdir(parents=True, exist_ok=True)

#     safe_fname = safe_name(filename)
#     out_path   = orig_dir / safe_fname
#     out_path.write_bytes(file_bytes)

#     doc_meta = {
#         "doc_id":        f"doc_{next_idx:03d}",
#         "original_name": filename,
#         "filename":      safe_fname,
#         "size":          len(file_bytes),
#         "uploaded_at":   datetime.utcnow().isoformat() + "Z",
#         "ocr_status":    "pending",
#     }
#     (doc_dir / "metadata.json").write_text(
#         json.dumps(doc_meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return doc_dir


# def list_session_documents(sess_dir: Path) -> list[dict]:
#     """Return list of document metadata dicts for a session."""
#     docs_dir = sess_dir / "documents"
#     if not docs_dir.exists():
#         return []
#     result = []
#     for d in sorted(docs_dir.iterdir()):
#         if not d.is_dir() or not d.name.startswith("doc_"):
#             continue
#         mf = d / "metadata.json"
#         if mf.exists():
#             try:
#                 m = json.loads(mf.read_text(encoding="utf-8"))
#                 m["_path"] = str(d)
#                 result.append(m)
#             except Exception:
#                 result.append({"doc_id": d.name, "_path": str(d)})
#     return result


# def get_combined_ocr_text(sess_dir: Path) -> str:
#     """
#     Merge OCR text from all doc_XXX/ocr/ folders within a session.
#     Checks processing/combined_ocr.txt ONLY if non-empty (cache).
#     Always rebuilds if cache is missing or empty.
#     """
#     combined_cache = sess_dir / "processing" / "combined_ocr.txt"

#     # ── Only trust the cache if it is non-empty ──────────────────────────────
#     if combined_cache.exists():
#         try:
#             cached = combined_cache.read_text(encoding="utf-8").strip()
#             if cached:
#                 return cached
#             else:
#                 # Cache exists but is empty — delete it and rebuild
#                 combined_cache.unlink(missing_ok=True)
#         except Exception:
#             combined_cache.unlink(missing_ok=True)

#     texts = []
#     for doc in list_session_documents(sess_dir):
#         doc_path   = Path(doc["_path"])
#         ocr_dir    = doc_path / "ocr"
#         if not ocr_dir.exists():
#             continue

#         t = ""

#         # ── Strategy 1: direct collect on ocr/ ───────────────────────────────
#         t = collect_ocr_text(ocr_dir)

#         # ── Strategy 2: look inside bundle subdirs (e.g. ocr/my_doc_pdf/) ────
#         if not t:
#             for sub in sorted(ocr_dir.iterdir()):
#                 if sub.is_dir():
#                     t = collect_ocr_text(sub)
#                     if t:
#                         break

#         # ── Strategy 3: rglob for any ocr_result.json under ocr/ ─────────────
#         if not t:
#             for ocr_json in ocr_dir.rglob("ocr_result.json"):
#                 try:
#                     data = load_json(ocr_json)
#                     if data and isinstance(data.get("pages", []), list):
#                         page_texts = []
#                         for page in data["pages"]:
#                             md = page.get("markdown", "").strip()
#                             if md:
#                                 page_texts.append(
#                                     f"--- Document JSON Page {page.get('index', 0)} ---\n{clean_markdown(md)}"
#                                 )
#                         if page_texts:
#                             t = "\n\n".join(page_texts)
#                             break
#                 except Exception:
#                     continue

#         # ── Strategy 4: rglob for any *.md files under ocr/ ──────────────────
#         if not t:
#             md_files = sorted(ocr_dir.rglob("*.md"))
#             if md_files:
#                 page_texts = []
#                 for md_file in md_files:
#                     try:
#                         content = md_file.read_text(encoding="utf-8").strip()
#                         if content:
#                             page_texts.append(f"--- {md_file.name} ---\n{content}")
#                     except Exception:
#                         continue
#                 t = "\n\n".join(page_texts)

#         if t:
#             texts.append(f"=== Document: {doc.get('original_name', doc['doc_id'])} ===\n{t}")

#     merged = "\n\n".join(texts)
#     if merged:
#         try:
#             combined_cache.parent.mkdir(parents=True, exist_ok=True)
#             combined_cache.write_text(merged, encoding="utf-8")
#         except Exception:
#             pass
#     return merged

# # ══════════════════════════════════════════════════════════════════════════════
# # VERIFICATION SYSTEM PROMPT
# # ══════════════════════════════════════════════════════════════════════════════

# VERIFICATION_SYSTEM_PROMPT = """
# You are an objective verifier comparing multiple-choice answers against an OCR-extracted document.
# Return a JSON array where each element corresponds to one input question ID and has the following keys:
# - id: (string) the question ID from the input
# - verification_status: one of ["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"]
# - confidence: numeric 0-100 estimating certainty of the verification
# - evidence_quote: short quote (<=250 chars) from the OCR that justifies the verdict, or "" if none
# - evidence_page: page identifier (e.g., "page_0003.md" or "Document JSON Page 2") where evidence was found, or "" if none
# - reasoning: plain-text explanation of how you reached the decision
# - suggested_answer: if the original selected answer seems wrong, suggest one of "A","B","C","D", or null

# Important:
# - Output only a single JSON array (or a fenced ```json block containing the array). Avoid extra commentary.
# - Be conservative: when evidence is partial, prefer PARTIALLY_SUPPORTED with a moderate confidence.
# - Use NOT_FOUND when no supporting text is present, not when contradictory evidence exists.
# """

# # ══════════════════════════════════════════════════════════════════════════════
# # SESSION FILESYSTEM HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def get_sessions_dir(username: str) -> Path:
#     return USER_DATA_DIR / username / "sessions"


# def create_new_session(username: str) -> tuple[str, Path]:
#     ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
#     sess_dir = get_sessions_dir(username) / ts
#     for sub in ("inputs", "documents", "processing", "outputs", "logs"):
#         (sess_dir / sub).mkdir(parents=True, exist_ok=True)
#     meta = {
#         "session_id":  ts,
#         "username":    username,
#         "created_at":  datetime.utcnow().isoformat() + "Z",
#         "status":      "created",
#         "doc_count":   0,
#         "company":     "",
#         "answer_mode": "",
#     }
#     (sess_dir / "metadata.json").write_text(
#         json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return ts, sess_dir


# def list_user_sessions(username: str) -> list[dict]:
#     """Return list of session metadata dicts, newest first."""
#     sessions_dir = get_sessions_dir(username)
#     if not sessions_dir.exists():
#         return []
#     result = []
#     for p in sorted(sessions_dir.iterdir(), reverse=True):
#         if not p.is_dir():
#             continue
#         meta_file = p / "metadata.json"
#         if meta_file.exists():
#             try:
#                 m = json.loads(meta_file.read_text(encoding="utf-8"))
#                 result.append(m)
#             except Exception:
#                 result.append({"session_id": p.name, "created_at": p.name})
#         else:
#             result.append({"session_id": p.name, "created_at": p.name})
#     return result


# def get_session_path(username: str, session_id: str) -> Path:
#     return get_sessions_dir(username) / session_id


# def update_session_meta(sess_dir: Path, updates: dict):
#     meta_file = sess_dir / "metadata.json"
#     try:
#         meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
#     except Exception:
#         meta = {}
#     meta.update(updates)
#     meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# def add_document_to_session(sess_dir: Path, file_bytes: bytes, filename: str) -> Path:
#     """
#     Save an uploaded file into the next available doc_XXX slot.
#     Returns the doc directory.
#     Layout:
#       session/documents/doc_001/original/<filename>
#       session/documents/doc_001/ocr/        (populated after OCR)
#       session/documents/doc_001/metadata.json
#     """
#     docs_dir = sess_dir / "documents"
#     existing = sorted([d for d in docs_dir.iterdir() if d.is_dir() and d.name.startswith("doc_")])
#     next_idx  = len(existing) + 1
#     doc_dir   = docs_dir / f"doc_{next_idx:03d}"
#     orig_dir  = doc_dir / "original"
#     orig_dir.mkdir(parents=True, exist_ok=True)
#     (doc_dir / "ocr").mkdir(parents=True, exist_ok=True)

#     safe_fname = safe_name(filename)
#     out_path   = orig_dir / safe_fname
#     out_path.write_bytes(file_bytes)

#     doc_meta = {
#         "doc_id":        f"doc_{next_idx:03d}",
#         "original_name": filename,
#         "filename":      safe_fname,
#         "size":          len(file_bytes),
#         "uploaded_at":   datetime.utcnow().isoformat() + "Z",
#         "ocr_status":    "pending",
#     }
#     (doc_dir / "metadata.json").write_text(
#         json.dumps(doc_meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return doc_dir


# def list_session_documents(sess_dir: Path) -> list[dict]:
#     """Return list of document metadata dicts for a session."""
#     docs_dir = sess_dir / "documents"
#     if not docs_dir.exists():
#         return []
#     result = []
#     for d in sorted(docs_dir.iterdir()):
#         if not d.is_dir() or not d.name.startswith("doc_"):
#             continue
#         mf = d / "metadata.json"
#         if mf.exists():
#             try:
#                 m = json.loads(mf.read_text(encoding="utf-8"))
#                 m["_path"] = str(d)
#                 result.append(m)
#             except Exception:
#                 result.append({"doc_id": d.name, "_path": str(d)})
#     return result


# def get_combined_ocr_text(sess_dir: Path) -> str:
#     """
#     Merge OCR text from all doc_XXX/ocr/ folders within a session.
#     Checks processing/combined_ocr.txt ONLY if non-empty (cache).
#     Always rebuilds if cache is missing or empty.
#     """
#     combined_cache = sess_dir / "processing" / "combined_ocr.txt"

#     # ── Only trust the cache if it is non-empty ──────────────────────────────
#     if combined_cache.exists():
#         try:
#             cached = combined_cache.read_text(encoding="utf-8").strip()
#             if cached:
#                 return cached
#             else:
#                 # Cache exists but is empty — delete it and rebuild
#                 combined_cache.unlink(missing_ok=True)
#         except Exception:
#             combined_cache.unlink(missing_ok=True)

#     texts = []
#     for doc in list_session_documents(sess_dir):
#         doc_path   = Path(doc["_path"])
#         ocr_dir    = doc_path / "ocr"
#         if not ocr_dir.exists():
#             continue

#         t = ""

#         # ── Strategy 1: direct collect on ocr/ ───────────────────────────────
#         t = collect_ocr_text(ocr_dir)

#         # ── Strategy 2: look inside bundle subdirs (e.g. ocr/my_doc_pdf/) ────
#         if not t:
#             for sub in sorted(ocr_dir.iterdir()):
#                 if sub.is_dir():
#                     t = collect_ocr_text(sub)
#                     if t:
#                         break

#         # ── Strategy 3: rglob for any ocr_result.json under ocr/ ─────────────
#         if not t:
#             for ocr_json in ocr_dir.rglob("ocr_result.json"):
#                 try:
#                     data = load_json(ocr_json)
#                     if data and isinstance(data.get("pages", []), list):
#                         page_texts = []
#                         for page in data["pages"]:
#                             md = page.get("markdown", "").strip()
#                             if md:
#                                 page_texts.append(
#                                     f"--- Document JSON Page {page.get('index', 0)} ---\n{clean_markdown(md)}"
#                                 )
#                         if page_texts:
#                             t = "\n\n".join(page_texts)
#                             break
#                 except Exception:
#                     continue

#         # ── Strategy 4: rglob for any *.md files under ocr/ ──────────────────
#         if not t:
#             md_files = sorted(ocr_dir.rglob("*.md"))
#             if md_files:
#                 page_texts = []
#                 for md_file in md_files:
#                     try:
#                         content = md_file.read_text(encoding="utf-8").strip()
#                         if content:
#                             page_texts.append(f"--- {md_file.name} ---\n{content}")
#                     except Exception:
#                         continue
#                 t = "\n\n".join(page_texts)

#         if t:
#             texts.append(f"=== Document: {doc.get('original_name', doc['doc_id'])} ===\n{t}")

#     merged = "\n\n".join(texts)
#     if merged:
#         try:
#             combined_cache.parent.mkdir(parents=True, exist_ok=True)
#             combined_cache.write_text(merged, encoding="utf-8")
#         except Exception:
#             pass
#     return merged

# # ══════════════════════════════════════════════════════════════════════════════
# # VERIFICATION SYSTEM PROMPT
# # ══════════════════════════════════════════════════════════════════════════════

# VERIFICATION_SYSTEM_PROMPT = """
# You are an objective verifier comparing multiple-choice answers against an OCR-extracted document.
# Return a JSON array where each element corresponds to one input question ID and has the following keys:
# - id: (string) the question ID from the input
# - verification_status: one of ["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"]
# - confidence: numeric 0-100 estimating certainty of the verification
# - evidence_quote: short quote (<=250 chars) from the OCR that justifies the verdict, or "" if none
# - evidence_page: page identifier (e.g., "page_0003.md" or "Document JSON Page 2") where evidence was found, or "" if none
# - reasoning: plain-text explanation of how you reached the decision
# - suggested_answer: if the original selected answer seems wrong, suggest one of "A","B","C","D", or null

# Important:
# - Output only a single JSON array (or a fenced ```json block containing the array). Avoid extra commentary.
# - Be conservative: when evidence is partial, prefer PARTIALLY_SUPPORTED with a moderate confidence.
# - Use NOT_FOUND when no supporting text is present, not when contradictory evidence exists.
# """

# # ══════════════════════════════════════════════════════════════════════════════
# # SESSION FILESYSTEM HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def get_sessions_dir(username: str) -> Path:
#     return USER_DATA_DIR / username / "sessions"


# def create_new_session(username: str) -> tuple[str, Path]:
#     ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
#     sess_dir = get_sessions_dir(username) / ts
#     for sub in ("inputs", "documents", "processing", "outputs", "logs"):
#         (sess_dir / sub).mkdir(parents=True, exist_ok=True)
#     meta = {
#         "session_id":  ts,
#         "username":    username,
#         "created_at":  datetime.utcnow().isoformat() + "Z",
#         "status":      "created",
#         "doc_count":   0,
#         "company":     "",
#         "answer_mode": "",
#     }
#     (sess_dir / "metadata.json").write_text(
#         json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return ts, sess_dir


# def list_user_sessions(username: str) -> list[dict]:
#     """Return list of session metadata dicts, newest first."""
#     sessions_dir = get_sessions_dir(username)
#     if not sessions_dir.exists():
#         return []
#     result = []
#     for p in sorted(sessions_dir.iterdir(), reverse=True):
#         if not p.is_dir():
#             continue
#         meta_file = p / "metadata.json"
#         if meta_file.exists():
#             try:
#                 m = json.loads(meta_file.read_text(encoding="utf-8"))
#                 result.append(m)
#             except Exception:
#                 result.append({"session_id": p.name, "created_at": p.name})
#         else:
#             result.append({"session_id": p.name, "created_at": p.name})
#     return result


# def get_session_path(username: str, session_id: str) -> Path:
#     return get_sessions_dir(username) / session_id


# def update_session_meta(sess_dir: Path, updates: dict):
#     meta_file = sess_dir / "metadata.json"
#     try:
#         meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
#     except Exception:
#         meta = {}
#     meta.update(updates)
#     meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# def add_document_to_session(sess_dir: Path, file_bytes: bytes, filename: str) -> Path:
#     """
#     Save an uploaded file into the next available doc_XXX slot.
#     Returns the doc directory.
#     Layout:
#       session/documents/doc_001/original/<filename>
#       session/documents/doc_001/ocr/        (populated after OCR)
#       session/documents/doc_001/metadata.json
#     """
#     docs_dir = sess_dir / "documents"
#     existing = sorted([d for d in docs_dir.iterdir() if d.is_dir() and d.name.startswith("doc_")])
#     next_idx  = len(existing) + 1
#     doc_dir   = docs_dir / f"doc_{next_idx:03d}"
#     orig_dir  = doc_dir / "original"
#     orig_dir.mkdir(parents=True, exist_ok=True)
#     (doc_dir / "ocr").mkdir(parents=True, exist_ok=True)

#     safe_fname = safe_name(filename)
#     out_path   = orig_dir / safe_fname
#     out_path.write_bytes(file_bytes)

#     doc_meta = {
#         "doc_id":        f"doc_{next_idx:03d}",
#         "original_name": filename,
#         "filename":      safe_fname,
#         "size":          len(file_bytes),
#         "uploaded_at":   datetime.utcnow().isoformat() + "Z",
#         "ocr_status":    "pending",
#     }
#     (doc_dir / "metadata.json").write_text(
#         json.dumps(doc_meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return doc_dir


# def list_session_documents(sess_dir: Path) -> list[dict]:
#     """Return list of document metadata dicts for a session."""
#     docs_dir = sess_dir / "documents"
#     if not docs_dir.exists():
#         return []
#     result = []
#     for d in sorted(docs_dir.iterdir()):
#         if not d.is_dir() or not d.name.startswith("doc_"):
#             continue
#         mf = d / "metadata.json"
#         if mf.exists():
#             try:
#                 m = json.loads(mf.read_text(encoding="utf-8"))
#                 m["_path"] = str(d)
#                 result.append(m)
#             except Exception:
#                 result.append({"doc_id": d.name, "_path": str(d)})
#     return result


# def get_combined_ocr_text(sess_dir: Path) -> str:
#     """
#     Merge OCR text from all doc_XXX/ocr/ folders within a session.
#     Checks processing/combined_ocr.txt ONLY if non-empty (cache).
#     Always rebuilds if cache is missing or empty.
#     """
#     combined_cache = sess_dir / "processing" / "combined_ocr.txt"

#     # ── Only trust the cache if it is non-empty ──────────────────────────────
#     if combined_cache.exists():
#         try:
#             cached = combined_cache.read_text(encoding="utf-8").strip()
#             if cached:
#                 return cached
#             else:
#                 # Cache exists but is empty — delete it and rebuild
#                 combined_cache.unlink(missing_ok=True)
#         except Exception:
#             combined_cache.unlink(missing_ok=True)

#     texts = []
#     for doc in list_session_documents(sess_dir):
#         doc_path   = Path(doc["_path"])
#         ocr_dir    = doc_path / "ocr"
#         if not ocr_dir.exists():
#             continue

#         t = ""

#         # ── Strategy 1: direct collect on ocr/ ───────────────────────────────
#         t = collect_ocr_text(ocr_dir)

#         # ── Strategy 2: look inside bundle subdirs (e.g. ocr/my_doc_pdf/) ────
#         if not t:
#             for sub in sorted(ocr_dir.iterdir()):
#                 if sub.is_dir():
#                     t = collect_ocr_text(sub)
#                     if t:
#                         break

#         # ── Strategy 3: rglob for any ocr_result.json under ocr/ ─────────────
#         if not t:
#             for ocr_json in ocr_dir.rglob("ocr_result.json"):
#                 try:
#                     data = load_json(ocr_json)
#                     if data and isinstance(data.get("pages", []), list):
#                         page_texts = []
#                         for page in data["pages"]:
#                             md = page.get("markdown", "").strip()
#                             if md:
#                                 page_texts.append(
#                                     f"--- Document JSON Page {page.get('index', 0)} ---\n{clean_markdown(md)}"
#                                 )
#                         if page_texts:
#                             t = "\n\n".join(page_texts)
#                             break
#                 except Exception:
#                     continue

#         # ── Strategy 4: rglob for any *.md files under ocr/ ──────────────────
#         if not t:
#             md_files = sorted(ocr_dir.rglob("*.md"))
#             if md_files:
#                 page_texts = []
#                 for md_file in md_files:
#                     try:
#                         content = md_file.read_text(encoding="utf-8").strip()
#                         if content:
#                             page_texts.append(f"--- {md_file.name} ---\n{content}")
#                     except Exception:
#                         continue
#                 t = "\n\n".join(page_texts)

#         if t:
#             texts.append(f"=== Document: {doc.get('original_name', doc['doc_id'])} ===\n{t}")

#     merged = "\n\n".join(texts)
#     if merged:
#         try:
#             combined_cache.parent.mkdir(parents=True, exist_ok=True)
#             combined_cache.write_text(merged, encoding="utf-8")
#         except Exception:
#             pass
#     return merged

# # ══════════════════════════════════════════════════════════════════════════════
# # VERIFICATION SYSTEM PROMPT
# # ══════════════════════════════════════════════════════════════════════════════

# VERIFICATION_SYSTEM_PROMPT = """
# You are an objective verifier comparing multiple-choice answers against an OCR-extracted document.
# Return a JSON array where each element corresponds to one input question ID and has the following keys:
# - id: (string) the question ID from the input
# - verification_status: one of ["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"]
# - confidence: numeric 0-100 estimating certainty of the verification
# - evidence_quote: short quote (<=250 chars) from the OCR that justifies the verdict, or "" if none
# - evidence_page: page identifier (e.g., "page_0003.md" or "Document JSON Page 2") where evidence was found, or "" if none
# - reasoning: plain-text explanation of how you reached the decision
# - suggested_answer: if the original selected answer seems wrong, suggest one of "A","B","C","D", or null

# Important:
# - Output only a single JSON array (or a fenced ```json block containing the array). Avoid extra commentary.
# - Be conservative: when evidence is partial, prefer PARTIALLY_SUPPORTED with a moderate confidence.
# - Use NOT_FOUND when no supporting text is present, not when contradictory evidence exists.
# """

# # ══════════════════════════════════════════════════════════════════════════════
# # SESSION FILESYSTEM HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def get_sessions_dir(username: str) -> Path:
#     return USER_DATA_DIR / username / "sessions"


# def create_new_session(username: str) -> tuple[str, Path]:
#     ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
#     sess_dir = get_sessions_dir(username) / ts
#     for sub in ("inputs", "documents", "processing", "outputs", "logs"):
#         (sess_dir / sub).mkdir(parents=True, exist_ok=True)
#     meta = {
#         "session_id":  ts,
#         "username":    username,
#         "created_at":  datetime.utcnow().isoformat() + "Z",
#         "status":      "created",
#         "doc_count":   0,
#         "company":     "",
#         "answer_mode": "",
#     }
#     (sess_dir / "metadata.json").write_text(
#         json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return ts, sess_dir


# def list_user_sessions(username: str) -> list[dict]:
#     """Return list of session metadata dicts, newest first."""
#     sessions_dir = get_sessions_dir(username)
#     if not sessions_dir.exists():
#         return []
#     result = []
#     for p in sorted(sessions_dir.iterdir(), reverse=True):
#         if not p.is_dir():
#             continue
#         meta_file = p / "metadata.json"
#         if meta_file.exists():
#             try:
#                 m = json.loads(meta_file.read_text(encoding="utf-8"))
#                 result.append(m)
#             except Exception:
#                 result.append({"session_id": p.name, "created_at": p.name})
#         else:
#             result.append({"session_id": p.name, "created_at": p.name})
#     return result


# def get_session_path(username: str, session_id: str) -> Path:
#     return get_sessions_dir(username) / session_id


# def update_session_meta(sess_dir: Path, updates: dict):
#     meta_file = sess_dir / "metadata.json"
#     try:
#         meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
#     except Exception:
#         meta = {}
#     meta.update(updates)
#     meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# def add_document_to_session(sess_dir: Path, file_bytes: bytes, filename: str) -> Path:
#     """
#     Save an uploaded file into the next available doc_XXX slot.
#     Returns the doc directory.
#     Layout:
#       session/documents/doc_001/original/<filename>
#       session/documents/doc_001/ocr/        (populated after OCR)
#       session/documents/doc_001/metadata.json
#     """
#     docs_dir = sess_dir / "documents"
#     existing = sorted([d for d in docs_dir.iterdir() if d.is_dir() and d.name.startswith("doc_")])
#     next_idx  = len(existing) + 1
#     doc_dir   = docs_dir / f"doc_{next_idx:03d}"
#     orig_dir  = doc_dir / "original"
#     orig_dir.mkdir(parents=True, exist_ok=True)
#     (doc_dir / "ocr").mkdir(parents=True, exist_ok=True)

#     safe_fname = safe_name(filename)
#     out_path   = orig_dir / safe_fname
#     out_path.write_bytes(file_bytes)

#     doc_meta = {
#         "doc_id":        f"doc_{next_idx:03d}",
#         "original_name": filename,
#         "filename":      safe_fname,
#         "size":          len(file_bytes),
#         "uploaded_at":   datetime.utcnow().isoformat() + "Z",
#         "ocr_status":    "pending",
#     }
#     (doc_dir / "metadata.json").write_text(
#         json.dumps(doc_meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return doc_dir


# def list_session_documents(sess_dir: Path) -> list[dict]:
#     """Return list of document metadata dicts for a session."""
#     docs_dir = sess_dir / "documents"
#     if not docs_dir.exists():
#         return []
#     result = []
#     for d in sorted(docs_dir.iterdir()):
#         if not d.is_dir() or not d.name.startswith("doc_"):
#             continue
#         mf = d / "metadata.json"
#         if mf.exists():
#             try:
#                 m = json.loads(mf.read_text(encoding="utf-8"))
#                 m["_path"] = str(d)
#                 result.append(m)
#             except Exception:
#                 result.append({"doc_id": d.name, "_path": str(d)})
#     return result


# def get_combined_ocr_text(sess_dir: Path) -> str:
#     """
#     Merge OCR text from all doc_XXX/ocr/ folders within a session.
#     Checks processing/combined_ocr.txt ONLY if non-empty (cache).
#     Always rebuilds if cache is missing or empty.
#     """
#     combined_cache = sess_dir / "processing" / "combined_ocr.txt"

#     # ── Only trust the cache if it is non-empty ──────────────────────────────
#     if combined_cache.exists():
#         try:
#             cached = combined_cache.read_text(encoding="utf-8").strip()
#             if cached:
#                 return cached
#             else:
#                 # Cache exists but is empty — delete it and rebuild
#                 combined_cache.unlink(missing_ok=True)
#         except Exception:
#             combined_cache.unlink(missing_ok=True)

#     texts = []
#     for doc in list_session_documents(sess_dir):
#         doc_path   = Path(doc["_path"])
#         ocr_dir    = doc_path / "ocr"
#         if not ocr_dir.exists():
#             continue

#         t = ""

#         # ── Strategy 1: direct collect on ocr/ ───────────────────────────────
#         t = collect_ocr_text(ocr_dir)

#         # ── Strategy 2: look inside bundle subdirs (e.g. ocr/my_doc_pdf/) ────
#         if not t:
#             for sub in sorted(ocr_dir.iterdir()):
#                 if sub.is_dir():
#                     t = collect_ocr_text(sub)
#                     if t:
#                         break

#         # ── Strategy 3: rglob for any ocr_result.json under ocr/ ─────────────
#         if not t:
#             for ocr_json in ocr_dir.rglob("ocr_result.json"):
#                 try:
#                     data = load_json(ocr_json)
#                     if data and isinstance(data.get("pages", []), list):
#                         page_texts = []
#                         for page in data["pages"]:
#                             md = page.get("markdown", "").strip()
#                             if md:
#                                 page_texts.append(
#                                     f"--- Document JSON Page {page.get('index', 0)} ---\n{clean_markdown(md)}"
#                                 )
#                         if page_texts:
#                             t = "\n\n".join(page_texts)
#                             break
#                 except Exception:
#                     continue

#         # ── Strategy 4: rglob for any *.md files under ocr/ ──────────────────
#         if not t:
#             md_files = sorted(ocr_dir.rglob("*.md"))
#             if md_files:
#                 page_texts = []
#                 for md_file in md_files:
#                     try:
#                         content = md_file.read_text(encoding="utf-8").strip()
#                         if content:
#                             page_texts.append(f"--- {md_file.name} ---\n{content}")
#                     except Exception:
#                         continue
#                 t = "\n\n".join(page_texts)

#         if t:
#             texts.append(f"=== Document: {doc.get('original_name', doc['doc_id'])} ===\n{t}")

#     merged = "\n\n".join(texts)
#     if merged:
#         try:
#             combined_cache.parent.mkdir(parents=True, exist_ok=True)
#             combined_cache.write_text(merged, encoding="utf-8")
#         except Exception:
#             pass
#     return merged

# # ══════════════════════════════════════════════════════════════════════════════
# # VERIFICATION SYSTEM PROMPT
# # ══════════════════════════════════════════════════════════════════════════════

# VERIFICATION_SYSTEM_PROMPT = """
# You are an objective verifier comparing multiple-choice answers against an OCR-extracted document.
# Return a JSON array where each element corresponds to one input question ID and has the following keys:
# - id: (string) the question ID from the input
# - verification_status: one of ["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"]
# - confidence: numeric 0-100 estimating certainty of the verification
# - evidence_quote: short quote (<=250 chars) from the OCR that justifies the verdict, or "" if none
# - evidence_page: page identifier (e.g., "page_0003.md" or "Document JSON Page 2") where evidence was found, or "" if none
# - reasoning: plain-text explanation of how you reached the decision
# - suggested_answer: if the original selected answer seems wrong, suggest one of "A","B","C","D", or null

# Important:
# - Output only a single JSON array (or a fenced ```json block containing the array). Avoid extra commentary.
# - Be conservative: when evidence is partial, prefer PARTIALLY_SUPPORTED with a moderate confidence.
# - Use NOT_FOUND when no supporting text is present, not when contradictory evidence exists.
# """

# # ══════════════════════════════════════════════════════════════════════════════
# # SESSION FILESYSTEM HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def get_sessions_dir(username: str) -> Path:
#     return USER_DATA_DIR / username / "sessions"


# def create_new_session(username: str) -> tuple[str, Path]:
#     ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
#     sess_dir = get_sessions_dir(username) / ts
#     for sub in ("inputs", "documents", "processing", "outputs", "logs"):
#         (sess_dir / sub).mkdir(parents=True, exist_ok=True)
#     meta = {
#         "session_id":  ts,
#         "username":    username,
#         "created_at":  datetime.utcnow().isoformat() + "Z",
#         "status":      "created",
#         "doc_count":   0,
#         "company":     "",
#         "answer_mode": "",
#     }
#     (sess_dir / "metadata.json").write_text(
#         json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return ts, sess_dir


# def list_user_sessions(username: str) -> list[dict]:
#     """Return list of session metadata dicts, newest first."""
#     sessions_dir = get_sessions_dir(username)
#     if not sessions_dir.exists():
#         return []
#     result = []
#     for p in sorted(sessions_dir.iterdir(), reverse=True):
#         if not p.is_dir():
#             continue
#         meta_file = p / "metadata.json"
#         if meta_file.exists():
#             try:
#                 m = json.loads(meta_file.read_text(encoding="utf-8"))
#                 result.append(m)
#             except Exception:
#                 result.append({"session_id": p.name, "created_at": p.name})
#         else:
#             result.append({"session_id": p.name, "created_at": p.name})
#     return result


# def get_session_path(username: str, session_id: str) -> Path:
#     return get_sessions_dir(username) / session_id


# def update_session_meta(sess_dir: Path, updates: dict):
#     meta_file = sess_dir / "metadata.json"
#     try:
#         meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
#     except Exception:
#         meta = {}
#     meta.update(updates)
#     meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# def add_document_to_session(sess_dir: Path, file_bytes: bytes, filename: str) -> Path:
#     """
#     Save an uploaded file into the next available doc_XXX slot.
#     Returns the doc directory.
#     Layout:
#       session/documents/doc_001/original/<filename>
#       session/documents/doc_001/ocr/        (populated after OCR)
#       session/documents/doc_001/metadata.json
#     """
#     docs_dir = sess_dir / "documents"
#     existing = sorted([d for d in docs_dir.iterdir() if d.is_dir() and d.name.startswith("doc_")])
#     next_idx  = len(existing) + 1
#     doc_dir   = docs_dir / f"doc_{next_idx:03d}"
#     orig_dir  = doc_dir / "original"
#     orig_dir.mkdir(parents=True, exist_ok=True)
#     (doc_dir / "ocr").mkdir(parents=True, exist_ok=True)

#     safe_fname = safe_name(filename)
#     out_path   = orig_dir / safe_fname
#     out_path.write_bytes(file_bytes)

#     doc_meta = {
#         "doc_id":        f"doc_{next_idx:03d}",
#         "original_name": filename,
#         "filename":      safe_fname,
#         "size":          len(file_bytes),
#         "uploaded_at":   datetime.utcnow().isoformat() + "Z",
#         "ocr_status":    "pending",
#     }
#     (doc_dir / "metadata.json").write_text(
#         json.dumps(doc_meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return doc_dir


# def list_session_documents(sess_dir: Path) -> list[dict]:
#     """Return list of document metadata dicts for a session."""
#     docs_dir = sess_dir / "documents"
#     if not docs_dir.exists():
#         return []
#     result = []
#     for d in sorted(docs_dir.iterdir()):
#         if not d.is_dir() or not d.name.startswith("doc_"):
#             continue
#         mf = d / "metadata.json"
#         if mf.exists():
#             try:
#                 m = json.loads(mf.read_text(encoding="utf-8"))
#                 m["_path"] = str(d)
#                 result.append(m)
#             except Exception:
#                 result.append({"doc_id": d.name, "_path": str(d)})
#     return result


# def get_combined_ocr_text(sess_dir: Path) -> str:
#     """
#     Merge OCR text from all doc_XXX/ocr/ folders within a session.
#     Checks processing/combined_ocr.txt ONLY if non-empty (cache).
#     Always rebuilds if cache is missing or empty.
#     """
#     combined_cache = sess_dir / "processing" / "combined_ocr.txt"

#     # ── Only trust the cache if it is non-empty ──────────────────────────────
#     if combined_cache.exists():
#         try:
#             cached = combined_cache.read_text(encoding="utf-8").strip()
#             if cached:
#                 return cached
#             else:
#                 # Cache exists but is empty — delete it and rebuild
#                 combined_cache.unlink(missing_ok=True)
#         except Exception:
#             combined_cache.unlink(missing_ok=True)

#     texts = []
#     for doc in list_session_documents(sess_dir):
#         doc_path   = Path(doc["_path"])
#         ocr_dir    = doc_path / "ocr"
#         if not ocr_dir.exists():
#             continue

#         t = ""

#         # ── Strategy 1: direct collect on ocr/ ───────────────────────────────
#         t = collect_ocr_text(ocr_dir)

#         # ── Strategy 2: look inside bundle subdirs (e.g. ocr/my_doc_pdf/) ────
#         if not t:
#             for sub in sorted(ocr_dir.iterdir()):
#                 if sub.is_dir():
#                     t = collect_ocr_text(sub)
#                     if t:
#                         break

#         # ── Strategy 3: rglob for any ocr_result.json under ocr/ ─────────────
#         if not t:
#             for ocr_json in ocr_dir.rglob("ocr_result.json"):
#                 try:
#                     data = load_json(ocr_json)
#                     if data and isinstance(data.get("pages", []), list):
#                         page_texts = []
#                         for page in data["pages"]:
#                             md = page.get("markdown", "").strip()
#                             if md:
#                                 page_texts.append(
#                                     f"--- Document JSON Page {page.get('index', 0)} ---\n{clean_markdown(md)}"
#                                 )
#                         if page_texts:
#                             t = "\n\n".join(page_texts)
#                             break
#                 except Exception:
#                     continue

#         # ── Strategy 4: rglob for any *.md files under ocr/ ──────────────────
#         if not t:
#             md_files = sorted(ocr_dir.rglob("*.md"))
#             if md_files:
#                 page_texts = []
#                 for md_file in md_files:
#                     try:
#                         content = md_file.read_text(encoding="utf-8").strip()
#                         if content:
#                             page_texts.append(f"--- {md_file.name} ---\n{content}")
#                     except Exception:
#                         continue
#                 t = "\n\n".join(page_texts)

#         if t:
#             texts.append(f"=== Document: {doc.get('original_name', doc['doc_id'])} ===\n{t}")

#     merged = "\n\n".join(texts)
#     if merged:
#         try:
#             combined_cache.parent.mkdir(parents=True, exist_ok=True)
#             combined_cache.write_text(merged, encoding="utf-8")
#         except Exception:
#             pass
#     return merged

# # ══════════════════════════════════════════════════════════════════════════════
# # VERIFICATION SYSTEM PROMPT
# # ══════════════════════════════════════════════════════════════════════════════

# VERIFICATION_SYSTEM_PROMPT = """
# You are an objective verifier comparing multiple-choice answers against an OCR-extracted document.
# Return a JSON array where each element corresponds to one input question ID and has the following keys:
# - id: (string) the question ID from the input
# - verification_status: one of ["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"]
# - confidence: numeric 0-100 estimating certainty of the verification
# - evidence_quote: short quote (<=250 chars) from the OCR that justifies the verdict, or "" if none
# - evidence_page: page identifier (e.g., "page_0003.md" or "Document JSON Page 2") where evidence was found, or "" if none
# - reasoning: plain-text explanation of how you reached the decision
# - suggested_answer: if the original selected answer seems wrong, suggest one of "A","B","C","D", or null

# Important:
# - Output only a single JSON array (or a fenced ```json block containing the array). Avoid extra commentary.
# - Be conservative: when evidence is partial, prefer PARTIALLY_SUPPORTED with a moderate confidence.
# - Use NOT_FOUND when no supporting text is present, not when contradictory evidence exists.
# """

# # ══════════════════════════════════════════════════════════════════════════════
# # SESSION FILESYSTEM HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def get_sessions_dir(username: str) -> Path:
#     return USER_DATA_DIR / username / "sessions"


# def create_new_session(username: str) -> tuple[str, Path]:
#     ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
#     sess_dir = get_sessions_dir(username) / ts
#     for sub in ("inputs", "documents", "processing", "outputs", "logs"):
#         (sess_dir / sub).mkdir(parents=True, exist_ok=True)
#     meta = {
#         "session_id":  ts,
#         "username":    username,
#         "created_at":  datetime.utcnow().isoformat() + "Z",
#         "status":      "created",
#         "doc_count":   0,
#         "company":     "",
#         "answer_mode": "",
#     }
#     (sess_dir / "metadata.json").write_text(
#         json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return ts, sess_dir


# def list_user_sessions(username: str) -> list[dict]:
#     """Return list of session metadata dicts, newest first."""
#     sessions_dir = get_sessions_dir(username)
#     if not sessions_dir.exists():
#         return []
#     result = []
#     for p in sorted(sessions_dir.iterdir(), reverse=True):
#         if not p.is_dir():
#             continue
#         meta_file = p / "metadata.json"
#         if meta_file.exists():
#             try:
#                 m = json.loads(meta_file.read_text(encoding="utf-8"))
#                 result.append(m)
#             except Exception:
#                 result.append({"session_id": p.name, "created_at": p.name})
#         else:
#             result.append({"session_id": p.name, "created_at": p.name})
#     return result


# def get_session_path(username: str, session_id: str) -> Path:
#     return get_sessions_dir(username) / session_id


# def update_session_meta(sess_dir: Path, updates: dict):
#     meta_file = sess_dir / "metadata.json"
#     try:
#         meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
#     except Exception:
#         meta = {}
#     meta.update(updates)
#     meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# def add_document_to_session(sess_dir: Path, file_bytes: bytes, filename: str) -> Path:
#     """
#     Save an uploaded file into the next available doc_XXX slot.
#     Returns the doc directory.
#     Layout:
#       session/documents/doc_001/original/<filename>
#       session/documents/doc_001/ocr/        (populated after OCR)
#       session/documents/doc_001/metadata.json
#     """
#     docs_dir = sess_dir / "documents"
#     existing = sorted([d for d in docs_dir.iterdir() if d.is_dir() and d.name.startswith("doc_")])
#     next_idx  = len(existing) + 1
#     doc_dir   = docs_dir / f"doc_{next_idx:03d}"
#     orig_dir  = doc_dir / "original"
#     orig_dir.mkdir(parents=True, exist_ok=True)
#     (doc_dir / "ocr").mkdir(parents=True, exist_ok=True)

#     safe_fname = safe_name(filename)
#     out_path   = orig_dir / safe_fname
#     out_path.write_bytes(file_bytes)

#     doc_meta = {
#         "doc_id":        f"doc_{next_idx:03d}",
#         "original_name": filename,
#         "filename":      safe_fname,
#         "size":          len(file_bytes),
#         "uploaded_at":   datetime.utcnow().isoformat() + "Z",
#         "ocr_status":    "pending",
#     }
#     (doc_dir / "metadata.json").write_text(
#         json.dumps(doc_meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return doc_dir


# def list_session_documents(sess_dir: Path) -> list[dict]:
#     """Return list of document metadata dicts for a session."""
#     docs_dir = sess_dir / "documents"
#     if not docs_dir.exists():
#         return []
#     result = []
#     for d in sorted(docs_dir.iterdir()):
#         if not d.is_dir() or not d.name.startswith("doc_"):
#             continue
#         mf = d / "metadata.json"
#         if mf.exists():
#             try:
#                 m = json.loads(mf.read_text(encoding="utf-8"))
#                 m["_path"] = str(d)
#                 result.append(m)
#             except Exception:
#                 result.append({"doc_id": d.name, "_path": str(d)})
#     return result


# def get_combined_ocr_text(sess_dir: Path) -> str:
#     """
#     Merge OCR text from all doc_XXX/ocr/ folders within a session.
#     Checks processing/combined_ocr.txt ONLY if non-empty (cache).
#     Always rebuilds if cache is missing or empty.
#     """
#     combined_cache = sess_dir / "processing" / "combined_ocr.txt"

#     # ── Only trust the cache if it is non-empty ──────────────────────────────
#     if combined_cache.exists():
#         try:
#             cached = combined_cache.read_text(encoding="utf-8").strip()
#             if cached:
#                 return cached
#             else:
#                 # Cache exists but is empty — delete it and rebuild
#                 combined_cache.unlink(missing_ok=True)
#         except Exception:
#             combined_cache.unlink(missing_ok=True)

#     texts = []
#     for doc in list_session_documents(sess_dir):
#         doc_path   = Path(doc["_path"])
#         ocr_dir    = doc_path / "ocr"
#         if not ocr_dir.exists():
#             continue

#         t = ""

#         # ── Strategy 1: direct collect on ocr/ ───────────────────────────────
#         t = collect_ocr_text(ocr_dir)

#         # ── Strategy 2: look inside bundle subdirs (e.g. ocr/my_doc_pdf/) ────
#         if not t:
#             for sub in sorted(ocr_dir.iterdir()):
#                 if sub.is_dir():
#                     t = collect_ocr_text(sub)
#                     if t:
#                         break

#         # ── Strategy 3: rglob for any ocr_result.json under ocr/ ─────────────
#         if not t:
#             for ocr_json in ocr_dir.rglob("ocr_result.json"):
#                 try:
#                     data = load_json(ocr_json)
#                     if data and isinstance(data.get("pages", []), list):
#                         page_texts = []
#                         for page in data["pages"]:
#                             md = page.get("markdown", "").strip()
#                             if md:
#                                 page_texts.append(
#                                     f"--- Document JSON Page {page.get('index', 0)} ---\n{clean_markdown(md)}"
#                                 )
#                         if page_texts:
#                             t = "\n\n".join(page_texts)
#                             break
#                 except Exception:
#                     continue

#         # ── Strategy 4: rglob for any *.md files under ocr/ ──────────────────
#         if not t:
#             md_files = sorted(ocr_dir.rglob("*.md"))
#             if md_files:
#                 page_texts = []
#                 for md_file in md_files:
#                     try:
#                         content = md_file.read_text(encoding="utf-8").strip()
#                         if content:
#                             page_texts.append(f"--- {md_file.name} ---\n{content}")
#                     except Exception:
#                         continue
#                 t = "\n\n".join(page_texts)

#         if t:
#             texts.append(f"=== Document: {doc.get('original_name', doc['doc_id'])} ===\n{t}")

#     merged = "\n\n".join(texts)
#     if merged:
#         try:
#             combined_cache.parent.mkdir(parents=True, exist_ok=True)
#             combined_cache.write_text(merged, encoding="utf-8")
#         except Exception:
#             pass
#     return merged

# # ══════════════════════════════════════════════════════════════════════════════
# # VERIFICATION SYSTEM PROMPT
# # ══════════════════════════════════════════════════════════════════════════════

# VERIFICATION_SYSTEM_PROMPT = """
# You are an objective verifier comparing multiple-choice answers against an OCR-extracted document.
# Return a JSON array where each element corresponds to one input question ID and has the following keys:
# - id: (string) the question ID from the input
# - verification_status: one of ["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"]
# - confidence: numeric 0-100 estimating certainty of the verification
# - evidence_quote: short quote (<=250 chars) from the OCR that justifies the verdict, or "" if none
# - evidence_page: page identifier (e.g., "page_0003.md" or "Document JSON Page 2") where evidence was found, or "" if none
# - reasoning: plain-text explanation of how you reached the decision
# - suggested_answer: if the original selected answer seems wrong, suggest one of "A","B","C","D", or null

# Important:
# - Output only a single JSON array (or a fenced ```json block containing the array). Avoid extra commentary.
# - Be conservative: when evidence is partial, prefer PARTIALLY_SUPPORTED with a moderate confidence.
# - Use NOT_FOUND when no supporting text is present, not when contradictory evidence exists.
# """

# # ══════════════════════════════════════════════════════════════════════════════
# # SESSION FILESYSTEM HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def get_sessions_dir(username: str) -> Path:
#     return USER_DATA_DIR / username / "sessions"


# def create_new_session(username: str) -> tuple[str, Path]:
#     ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
#     sess_dir = get_sessions_dir(username) / ts
#     for sub in ("inputs", "documents", "processing", "outputs", "logs"):
#         (sess_dir / sub).mkdir(parents=True, exist_ok=True)
#     meta = {
#         "session_id":  ts,
#         "username":    username,
#         "created_at":  datetime.utcnow().isoformat() + "Z",
#         "status":      "created",
#         "doc_count":   0,
#         "company":     "",
#         "answer_mode": "",
#     }
#     (sess_dir / "metadata.json").write_text(
#         json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return ts, sess_dir


# def list_user_sessions(username: str) -> list[dict]:
#     """Return list of session metadata dicts, newest first."""
#     sessions_dir = get_sessions_dir(username)
#     if not sessions_dir.exists():
#         return []
#     result = []
#     for p in sorted(sessions_dir.iterdir(), reverse=True):
#         if not p.is_dir():
#             continue
#         meta_file = p / "metadata.json"
#         if meta_file.exists():
#             try:
#                 m = json.loads(meta_file.read_text(encoding="utf-8"))
#                 result.append(m)
#             except Exception:
#                 result.append({"session_id": p.name, "created_at": p.name})
#         else:
#             result.append({"session_id": p.name, "created_at": p.name})
#     return result


# def get_session_path(username: str, session_id: str) -> Path:
#     return get_sessions_dir(username) / session_id


# def update_session_meta(sess_dir: Path, updates: dict):
#     meta_file = sess_dir / "metadata.json"
#     try:
#         meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
#     except Exception:
#         meta = {}
#     meta.update(updates)
#     meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# def add_document_to_session(sess_dir: Path, file_bytes: bytes, filename: str) -> Path:
#     """
#     Save an uploaded file into the next available doc_XXX slot.
#     Returns the doc directory.
#     Layout:
#       session/documents/doc_001/original/<filename>
#       session/documents/doc_001/ocr/        (populated after OCR)
#       session/documents/doc_001/metadata.json
#     """
#     docs_dir = sess_dir / "documents"
#     existing = sorted([d for d in docs_dir.iterdir() if d.is_dir() and d.name.startswith("doc_")])
#     next_idx  = len(existing) + 1
#     doc_dir   = docs_dir / f"doc_{next_idx:03d}"
#     orig_dir  = doc_dir / "original"
#     orig_dir.mkdir(parents=True, exist_ok=True)
#     (doc_dir / "ocr").mkdir(parents=True, exist_ok=True)

#     safe_fname = safe_name(filename)
#     out_path   = orig_dir / safe_fname
#     out_path.write_bytes(file_bytes)

#     doc_meta = {
#         "doc_id":        f"doc_{next_idx:03d}",
#         "original_name": filename,
#         "filename":      safe_fname,
#         "size":          len(file_bytes),
#         "uploaded_at":   datetime.utcnow().isoformat() + "Z",
#         "ocr_status":    "pending",
#     }
#     (doc_dir / "metadata.json").write_text(
#         json.dumps(doc_meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return doc_dir


# def list_session_documents(sess_dir: Path) -> list[dict]:
#     """Return list of document metadata dicts for a session."""
#     docs_dir = sess_dir / "documents"
#     if not docs_dir.exists():
#         return []
#     result = []
#     for d in sorted(docs_dir.iterdir()):
#         if not d.is_dir() or not d.name.startswith("doc_"):
#             continue
#         mf = d / "metadata.json"
#         if mf.exists():
#             try:
#                 m = json.loads(mf.read_text(encoding="utf-8"))
#                 m["_path"] = str(d)
#                 result.append(m)
#             except Exception:
#                 result.append({"doc_id": d.name, "_path": str(d)})
#     return result


# def get_combined_ocr_text(sess_dir: Path) -> str:
#     """
#     Merge OCR text from all doc_XXX/ocr/ folders within a session.
#     Checks processing/combined_ocr.txt ONLY if non-empty (cache).
#     Always rebuilds if cache is missing or empty.
#     """
#     combined_cache = sess_dir / "processing" / "combined_ocr.txt"

#     # ── Only trust the cache if it is non-empty ──────────────────────────────
#     if combined_cache.exists():
#         try:
#             cached = combined_cache.read_text(encoding="utf-8").strip()
#             if cached:
#                 return cached
#             else:
#                 # Cache exists but is empty — delete it and rebuild
#                 combined_cache.unlink(missing_ok=True)
#         except Exception:
#             combined_cache.unlink(missing_ok=True)

#     texts = []
#     for doc in list_session_documents(sess_dir):
#         doc_path   = Path(doc["_path"])
#         ocr_dir    = doc_path / "ocr"
#         if not ocr_dir.exists():
#             continue

#         t = ""

#         # ── Strategy 1: direct collect on ocr/ ───────────────────────────────
#         t = collect_ocr_text(ocr_dir)

#         # ── Strategy 2: look inside bundle subdirs (e.g. ocr/my_doc_pdf/) ────
#         if not t:
#             for sub in sorted(ocr_dir.iterdir()):
#                 if sub.is_dir():
#                     t = collect_ocr_text(sub)
#                     if t:
#                         break

#         # ── Strategy 3: rglob for any ocr_result.json under ocr/ ─────────────
#         if not t:
#             for ocr_json in ocr_dir.rglob("ocr_result.json"):
#                 try:
#                     data = load_json(ocr_json)
#                     if data and isinstance(data.get("pages", []), list):
#                         page_texts = []
#                         for page in data["pages"]:
#                             md = page.get("markdown", "").strip()
#                             if md:
#                                 page_texts.append(
#                                     f"--- Document JSON Page {page.get('index', 0)} ---\n{clean_markdown(md)}"
#                                 )
#                         if page_texts:
#                             t = "\n\n".join(page_texts)
#                             break
#                 except Exception:
#                     continue

#         # ── Strategy 4: rglob for any *.md files under ocr/ ──────────────────
#         if not t:
#             md_files = sorted(ocr_dir.rglob("*.md"))
#             if md_files:
#                 page_texts = []
#                 for md_file in md_files:
#                     try:
#                         content = md_file.read_text(encoding="utf-8").strip()
#                         if content:
#                             page_texts.append(f"--- {md_file.name} ---\n{content}")
#                     except Exception:
#                         continue
#                 t = "\n\n".join(page_texts)

#         if t:
#             texts.append(f"=== Document: {doc.get('original_name', doc['doc_id'])} ===\n{t}")

#     merged = "\n\n".join(texts)
#     if merged:
#         try:
#             combined_cache.parent.mkdir(parents=True, exist_ok=True)
#             combined_cache.write_text(merged, encoding="utf-8")
#         except Exception:
#             pass
#     return merged

# # ══════════════════════════════════════════════════════════════════════════════
# # VERIFICATION SYSTEM PROMPT
# # ══════════════════════════════════════════════════════════════════════════════

# VERIFICATION_SYSTEM_PROMPT = """
# You are an objective verifier comparing multiple-choice answers against an OCR-extracted document.
# Return a JSON array where each element corresponds to one input question ID and has the following keys:
# - id: (string) the question ID from the input
# - verification_status: one of ["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"]
# - confidence: numeric 0-100 estimating certainty of the verification
# - evidence_quote: short quote (<=250 chars) from the OCR that justifies the verdict, or "" if none
# - evidence_page: page identifier (e.g., "page_0003.md" or "Document JSON Page 2") where evidence was found, or "" if none
# - reasoning: plain-text explanation of how you reached the decision
# - suggested_answer: if the original selected answer seems wrong, suggest one of "A","B","C","D", or null

# Important:
# - Output only a single JSON array (or a fenced ```json block containing the array). Avoid extra commentary.
# - Be conservative: when evidence is partial, prefer PARTIALLY_SUPPORTED with a moderate confidence.
# - Use NOT_FOUND when no supporting text is present, not when contradictory evidence exists.
# """

# # ══════════════════════════════════════════════════════════════════════════════
# # SESSION FILESYSTEM HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def get_sessions_dir(username: str) -> Path:
#     return USER_DATA_DIR / username / "sessions"


# def create_new_session(username: str) -> tuple[str, Path]:
#     ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
#     sess_dir = get_sessions_dir(username) / ts
#     for sub in ("inputs", "documents", "processing", "outputs", "logs"):
#         (sess_dir / sub).mkdir(parents=True, exist_ok=True)
#     meta = {
#         "session_id":  ts,
#         "username":    username,
#         "created_at":  datetime.utcnow().isoformat() + "Z",
#         "status":      "created",
#         "doc_count":   0,
#         "company":     "",
#         "answer_mode": "",
#     }
#     (sess_dir / "metadata.json").write_text(
#         json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return ts, sess_dir


# def list_user_sessions(username: str) -> list[dict]:
#     """Return list of session metadata dicts, newest first."""
#     sessions_dir = get_sessions_dir(username)
#     if not sessions_dir.exists():
#         return []
#     result = []
#     for p in sorted(sessions_dir.iterdir(), reverse=True):
#         if not p.is_dir():
#             continue
#         meta_file = p / "metadata.json"
#         if meta_file.exists():
#             try:
#                 m = json.loads(meta_file.read_text(encoding="utf-8"))
#                 result.append(m)
#             except Exception:
#                 result.append({"session_id": p.name, "created_at": p.name})
#         else:
#             result.append({"session_id": p.name, "created_at": p.name})
#     return result


# def get_session_path(username: str, session_id: str) -> Path:
#     return get_sessions_dir(username) / session_id


# def update_session_meta(sess_dir: Path, updates: dict):
#     meta_file = sess_dir / "metadata.json"
#     try:
#         meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
#     except Exception:
#         meta = {}
#     meta.update(updates)
#     meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# def add_document_to_session(sess_dir: Path, file_bytes: bytes, filename: str) -> Path:
#     """
#     Save an uploaded file into the next available doc_XXX slot.
#     Returns the doc directory.
#     Layout:
#       session/documents/doc_001/original/<filename>
#       session/documents/doc_001/ocr/        (populated after OCR)
#       session/documents/doc_001/metadata.json
#     """
#     docs_dir = sess_dir / "documents"
#     existing = sorted([d for d in docs_dir.iterdir() if d.is_dir() and d.name.startswith("doc_")])
#     next_idx  = len(existing) + 1
#     doc_dir   = docs_dir / f"doc_{next_idx:03d}"
#     orig_dir  = doc_dir / "original"
#     orig_dir.mkdir(parents=True, exist_ok=True)
#     (doc_dir / "ocr").mkdir(parents=True, exist_ok=True)

#     safe_fname = safe_name(filename)
#     out_path   = orig_dir / safe_fname
#     out_path.write_bytes(file_bytes)

#     doc_meta = {
#         "doc_id":        f"doc_{next_idx:03d}",
#         "original_name": filename,
#         "filename":      safe_fname,
#         "size":          len(file_bytes),
#         "uploaded_at":   datetime.utcnow().isoformat() + "Z",
#         "ocr_status":    "pending",
#     }
#     (doc_dir / "metadata.json").write_text(
#         json.dumps(doc_meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return doc_dir


# def list_session_documents(sess_dir: Path) -> list[dict]:
#     """Return list of document metadata dicts for a session."""
#     docs_dir = sess_dir / "documents"
#     if not docs_dir.exists():
#         return []
#     result = []
#     for d in sorted(docs_dir.iterdir()):
#         if not d.is_dir() or not d.name.startswith("doc_"):
#             continue
#         mf = d / "metadata.json"
#         if mf.exists():
#             try:
#                 m = json.loads(mf.read_text(encoding="utf-8"))
#                 m["_path"] = str(d)
#                 result.append(m)
#             except Exception:
#                 result.append({"doc_id": d.name, "_path": str(d)})
#     return result


# def get_combined_ocr_text(sess_dir: Path) -> str:
#     """
#     Merge OCR text from all doc_XXX/ocr/ folders within a session.
#     Checks processing/combined_ocr.txt ONLY if non-empty (cache).
#     Always rebuilds if cache is missing or empty.
#     """
#     combined_cache = sess_dir / "processing" / "combined_ocr.txt"

#     # ── Only trust the cache if it is non-empty ──────────────────────────────
#     if combined_cache.exists():
#         try:
#             cached = combined_cache.read_text(encoding="utf-8").strip()
#             if cached:
#                 return cached
#             else:
#                 # Cache exists but is empty — delete it and rebuild
#                 combined_cache.unlink(missing_ok=True)
#         except Exception:
#             combined_cache.unlink(missing_ok=True)

#     texts = []
#     for doc in list_session_documents(sess_dir):
#         doc_path   = Path(doc["_path"])
#         ocr_dir    = doc_path / "ocr"
#         if not ocr_dir.exists():
#             continue

#         t = ""

#         # ── Strategy 1: direct collect on ocr/ ───────────────────────────────
#         t = collect_ocr_text(ocr_dir)

#         # ── Strategy 2: look inside bundle subdirs (e.g. ocr/my_doc_pdf/) ────
#         if not t:
#             for sub in sorted(ocr_dir.iterdir()):
#                 if sub.is_dir():
#                     t = collect_ocr_text(sub)
#                     if t:
#                         break

#         # ── Strategy 3: rglob for any ocr_result.json under ocr/ ─────────────
#         if not t:
#             for ocr_json in ocr_dir.rglob("ocr_result.json"):
#                 try:
#                     data = load_json(ocr_json)
#                     if data and isinstance(data.get("pages", []), list):
#                         page_texts = []
#                         for page in data["pages"]:
#                             md = page.get("markdown", "").strip()
#                             if md:
#                                 page_texts.append(
#                                     f"--- Document JSON Page {page.get('index', 0)} ---\n{clean_markdown(md)}"
#                                 )
#                         if page_texts:
#                             t = "\n\n".join(page_texts)
#                             break
#                 except Exception:
#                     continue

#         # ── Strategy 4: rglob for any *.md files under ocr/ ──────────────────
#         if not t:
#             md_files = sorted(ocr_dir.rglob("*.md"))
#             if md_files:
#                 page_texts = []
#                 for md_file in md_files:
#                     try:
#                         content = md_file.read_text(encoding="utf-8").strip()
#                         if content:
#                             page_texts.append(f"--- {md_file.name} ---\n{content}")
#                     except Exception:
#                         continue
#                 t = "\n\n".join(page_texts)

#         if t:
#             texts.append(f"=== Document: {doc.get('original_name', doc['doc_id'])} ===\n{t}")

#     merged = "\n\n".join(texts)
#     if merged:
#         try:
#             combined_cache.parent.mkdir(parents=True, exist_ok=True)
#             combined_cache.write_text(merged, encoding="utf-8")
#         except Exception:
#             pass
#     return merged

# # ══════════════════════════════════════════════════════════════════════════════
# # VERIFICATION SYSTEM PROMPT
# # ══════════════════════════════════════════════════════════════════════════════

# VERIFICATION_SYSTEM_PROMPT = """
# You are an objective verifier comparing multiple-choice answers against an OCR-extracted document.
# Return a JSON array where each element corresponds to one input question ID and has the following keys:
# - id: (string) the question ID from the input
# - verification_status: one of ["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"]
# - confidence: numeric 0-100 estimating certainty of the verification
# - evidence_quote: short quote (<=250 chars) from the OCR that justifies the verdict, or "" if none
# - evidence_page: page identifier (e.g., "page_0003.md" or "Document JSON Page 2") where evidence was found, or "" if none
# - reasoning: plain-text explanation of how you reached the decision
# - suggested_answer: if the original selected answer seems wrong, suggest one of "A","B","C","D", or null

# Important:
# - Output only a single JSON array (or a fenced ```json block containing the array). Avoid extra commentary.
# - Be conservative: when evidence is partial, prefer PARTIALLY_SUPPORTED with a moderate confidence.
# - Use NOT_FOUND when no supporting text is present, not when contradictory evidence exists.
# """

# # ══════════════════════════════════════════════════════════════════════════════
# # SESSION FILESYSTEM HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def get_sessions_dir(username: str) -> Path:
#     return USER_DATA_DIR / username / "sessions"


# def create_new_session(username: str) -> tuple[str, Path]:
#     ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
#     sess_dir = get_sessions_dir(username) / ts
#     for sub in ("inputs", "documents", "processing", "outputs", "logs"):
#         (sess_dir / sub).mkdir(parents=True, exist_ok=True)
#     meta = {
#         "session_id":  ts,
#         "username":    username,
#         "created_at":  datetime.utcnow().isoformat() + "Z",
#         "status":      "created",
#         "doc_count":   0,
#         "company":     "",
#         "answer_mode": "",
#     }
#     (sess_dir / "metadata.json").write_text(
#         json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return ts, sess_dir


# def list_user_sessions(username: str) -> list[dict]:
#     """Return list of session metadata dicts, newest first."""
#     sessions_dir = get_sessions_dir(username)
#     if not sessions_dir.exists():
#         return []
#     result = []
#     for p in sorted(sessions_dir.iterdir(), reverse=True):
#         if not p.is_dir():
#             continue
#         meta_file = p / "metadata.json"
#         if meta_file.exists():
#             try:
#                 m = json.loads(meta_file.read_text(encoding="utf-8"))
#                 result.append(m)
#             except Exception:
#                 result.append({"session_id": p.name, "created_at": p.name})
#         else:
#             result.append({"session_id": p.name, "created_at": p.name})
#     return result


# def get_session_path(username: str, session_id: str) -> Path:
#     return get_sessions_dir(username) / session_id


# def update_session_meta(sess_dir: Path, updates: dict):
#     meta_file = sess_dir / "metadata.json"
#     try:
#         meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
#     except Exception:
#         meta = {}
#     meta.update(updates)
#     meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# def add_document_to_session(sess_dir: Path, file_bytes: bytes, filename: str) -> Path:
#     """
#     Save an uploaded file into the next available doc_XXX slot.
#     Returns the doc directory.
#     Layout:
#       session/documents/doc_001/original/<filename>
#       session/documents/doc_001/ocr/        (populated after OCR)
#       session/documents/doc_001/metadata.json
#     """
#     docs_dir = sess_dir / "documents"
#     existing = sorted([d for d in docs_dir.iterdir() if d.is_dir() and d.name.startswith("doc_")])
#     next_idx  = len(existing) + 1
#     doc_dir   = docs_dir / f"doc_{next_idx:03d}"
#     orig_dir  = doc_dir / "original"
#     orig_dir.mkdir(parents=True, exist_ok=True)
#     (doc_dir / "ocr").mkdir(parents=True, exist_ok=True)

#     safe_fname = safe_name(filename)
#     out_path   = orig_dir / safe_fname
#     out_path.write_bytes(file_bytes)

#     doc_meta = {
#         "doc_id":        f"doc_{next_idx:03d}",
#         "original_name": filename,
#         "filename":      safe_fname,
#         "size":          len(file_bytes),
#         "uploaded_at":   datetime.utcnow().isoformat() + "Z",
#         "ocr_status":    "pending",
#     }
#     (doc_dir / "metadata.json").write_text(
#         json.dumps(doc_meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return doc_dir


# def list_session_documents(sess_dir: Path) -> list[dict]:
#     """Return list of document metadata dicts for a session."""
#     docs_dir = sess_dir / "documents"
#     if not docs_dir.exists():
#         return []
#     result = []
#     for d in sorted(docs_dir.iterdir()):
#         if not d.is_dir() or not d.name.startswith("doc_"):
#             continue
#         mf = d / "metadata.json"
#         if mf.exists():
#             try:
#                 m = json.loads(mf.read_text(encoding="utf-8"))
#                 m["_path"] = str(d)
#                 result.append(m)
#             except Exception:
#                 result.append({"doc_id": d.name, "_path": str(d)})
#     return result


# def get_combined_ocr_text(sess_dir: Path) -> str:
#     """
#     Merge OCR text from all doc_XXX/ocr/ folders within a session.
#     Checks processing/combined_ocr.txt ONLY if non-empty (cache).
#     Always rebuilds if cache is missing or empty.
#     """
#     combined_cache = sess_dir / "processing" / "combined_ocr.txt"

#     # ── Only trust the cache if it is non-empty ──────────────────────────────
#     if combined_cache.exists():
#         try:
#             cached = combined_cache.read_text(encoding="utf-8").strip()
#             if cached:
#                 return cached
#             else:
#                 # Cache exists but is empty — delete it and rebuild
#                 combined_cache.unlink(missing_ok=True)
#         except Exception:
#             combined_cache.unlink(missing_ok=True)

#     texts = []
#     for doc in list_session_documents(sess_dir):
#         doc_path   = Path(doc["_path"])
#         ocr_dir    = doc_path / "ocr"
#         if not ocr_dir.exists():
#             continue

#         t = ""

#         # ── Strategy 1: direct collect on ocr/ ───────────────────────────────
#         t = collect_ocr_text(ocr_dir)

#         # ── Strategy 2: look inside bundle subdirs (e.g. ocr/my_doc_pdf/) ────
#         if not t:
#             for sub in sorted(ocr_dir.iterdir()):
#                 if sub.is_dir():
#                     t = collect_ocr_text(sub)
#                     if t:
#                         break

#         # ── Strategy 3: rglob for any ocr_result.json under ocr/ ─────────────
#         if not t:
#             for ocr_json in ocr_dir.rglob("ocr_result.json"):
#                 try:
#                     data = load_json(ocr_json)
#                     if data and isinstance(data.get("pages", []), list):
#                         page_texts = []
#                         for page in data["pages"]:
#                             md = page.get("markdown", "").strip()
#                             if md:
#                                 page_texts.append(
#                                     f"--- Document JSON Page {page.get('index', 0)} ---\n{clean_markdown(md)}"
#                                 )
#                         if page_texts:
#                             t = "\n\n".join(page_texts)
#                             break
#                 except Exception:
#                     continue

#         # ── Strategy 4: rglob for any *.md files under ocr/ ──────────────────
#         if not t:
#             md_files = sorted(ocr_dir.rglob("*.md"))
#             if md_files:
#                 page_texts = []
#                 for md_file in md_files:
#                     try:
#                         content = md_file.read_text(encoding="utf-8").strip()
#                         if content:
#                             page_texts.append(f"--- {md_file.name} ---\n{content}")
#                     except Exception:
#                         continue
#                 t = "\n\n".join(page_texts)

#         if t:
#             texts.append(f"=== Document: {doc.get('original_name', doc['doc_id'])} ===\n{t}")

#     merged = "\n\n".join(texts)
#     if merged:
#         try:
#             combined_cache.parent.mkdir(parents=True, exist_ok=True)
#             combined_cache.write_text(merged, encoding="utf-8")
#         except Exception:
#             pass
#     return merged

# # ══════════════════════════════════════════════════════════════════════════════
# # VERIFICATION SYSTEM PROMPT
# # ══════════════════════════════════════════════════════════════════════════════

# VERIFICATION_SYSTEM_PROMPT = """
# You are an objective verifier comparing multiple-choice answers against an OCR-extracted document.
# Return a JSON array where each element corresponds to one input question ID and has the following keys:
# - id: (string) the question ID from the input
# - verification_status: one of ["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"]
# - confidence: numeric 0-100 estimating certainty of the verification
# - evidence_quote: short quote (<=250 chars) from the OCR that justifies the verdict, or "" if none
# - evidence_page: page identifier (e.g., "page_0003.md" or "Document JSON Page 2") where evidence was found, or "" if none
# - reasoning: plain-text explanation of how you reached the decision
# - suggested_answer: if the original selected answer seems wrong, suggest one of "A","B","C","D", or null

# Important:
# - Output only a single JSON array (or a fenced ```json block containing the array). Avoid extra commentary.
# - Be conservative: when evidence is partial, prefer PARTIALLY_SUPPORTED with a moderate confidence.
# - Use NOT_FOUND when no supporting text is present, not when contradictory evidence exists.
# """

# # ══════════════════════════════════════════════════════════════════════════════
# # SESSION FILESYSTEM HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def get_sessions_dir(username: str) -> Path:
#     return USER_DATA_DIR / username / "sessions"


# def create_new_session(username: str) -> tuple[str, Path]:
#     ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
#     sess_dir = get_sessions_dir(username) / ts
#     for sub in ("inputs", "documents", "processing", "outputs", "logs"):
#         (sess_dir / sub).mkdir(parents=True, exist_ok=True)
#     meta = {
#         "session_id":  ts,
#         "username":    username,
#         "created_at":  datetime.utcnow().isoformat() + "Z",
#         "status":      "created",
#         "doc_count":   0,
#         "company":     "",
#         "answer_mode": "",
#     }
#     (sess_dir / "metadata.json").write_text(
#         json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return ts, sess_dir


# def list_user_sessions(username: str) -> list[dict]:
#     """Return list of session metadata dicts, newest first."""
#     sessions_dir = get_sessions_dir(username)
#     if not sessions_dir.exists():
#         return []
#     result = []
#     for p in sorted(sessions_dir.iterdir(), reverse=True):
#         if not p.is_dir():
#             continue
#         meta_file = p / "metadata.json"
#         if meta_file.exists():
#             try:
#                 m = json.loads(meta_file.read_text(encoding="utf-8"))
#                 result.append(m)
#             except Exception:
#                 result.append({"session_id": p.name, "created_at": p.name})
#         else:
#             result.append({"session_id": p.name, "created_at": p.name})
#     return result


# def get_session_path(username: str, session_id: str) -> Path:
#     return get_sessions_dir(username) / session_id


# def update_session_meta(sess_dir: Path, updates: dict):
#     meta_file = sess_dir / "metadata.json"
#     try:
#         meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
#     except Exception:
#         meta = {}
#     meta.update(updates)
#     meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# def add_document_to_session(sess_dir: Path, file_bytes: bytes, filename: str) -> Path:
#     """
#     Save an uploaded file into the next available doc_XXX slot.
#     Returns the doc directory.
#     Layout:
#       session/documents/doc_001/original/<filename>
#       session/documents/doc_001/ocr/        (populated after OCR)
#       session/documents/doc_001/metadata.json
#     """
#     docs_dir = sess_dir / "documents"
#     existing = sorted([d for d in docs_dir.iterdir() if d.is_dir() and d.name.startswith("doc_")])
#     next_idx  = len(existing) + 1
#     doc_dir   = docs_dir / f"doc_{next_idx:03d}"
#     orig_dir  = doc_dir / "original"
#     orig_dir.mkdir(parents=True, exist_ok=True)
#     (doc_dir / "ocr").mkdir(parents=True, exist_ok=True)

#     safe_fname = safe_name(filename)
#     out_path   = orig_dir / safe_fname
#     out_path.write_bytes(file_bytes)

#     doc_meta = {
#         "doc_id":        f"doc_{next_idx:03d}",
#         "original_name": filename,
#         "filename":      safe_fname,
#         "size":          len(file_bytes),
#         "uploaded_at":   datetime.utcnow().isoformat() + "Z",
#         "ocr_status":    "pending",
#     }
#     (doc_dir / "metadata.json").write_text(
#         json.dumps(doc_meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return doc_dir


# def list_session_documents(sess_dir: Path) -> list[dict]:
#     """Return list of document metadata dicts for a session."""
#     docs_dir = sess_dir / "documents"
#     if not docs_dir.exists():
#         return []
#     result = []
#     for d in sorted(docs_dir.iterdir()):
#         if not d.is_dir() or not d.name.startswith("doc_"):
#             continue
#         mf = d / "metadata.json"
#         if mf.exists():
#             try:
#                 m = json.loads(mf.read_text(encoding="utf-8"))
#                 m["_path"] = str(d)
#                 result.append(m)
#             except Exception:
#                 result.append({"doc_id": d.name, "_path": str(d)})
#     return result


# def get_combined_ocr_text(sess_dir: Path) -> str:
#     """
#     Merge OCR text from all doc_XXX/ocr/ folders within a session.
#     Checks processing/combined_ocr.txt ONLY if non-empty (cache).
#     Always rebuilds if cache is missing or empty.
#     """
#     combined_cache = sess_dir / "processing" / "combined_ocr.txt"

#     # ── Only trust the cache if it is non-empty ──────────────────────────────
#     if combined_cache.exists():
#         try:
#             cached = combined_cache.read_text(encoding="utf-8").strip()
#             if cached:
#                 return cached
#             else:
#                 # Cache exists but is empty — delete it and rebuild
#                 combined_cache.unlink(missing_ok=True)
#         except Exception:
#             combined_cache.unlink(missing_ok=True)

#     texts = []
#     for doc in list_session_documents(sess_dir):
#         doc_path   = Path(doc["_path"])
#         ocr_dir    = doc_path / "ocr"
#         if not ocr_dir.exists():
#             continue

#         t = ""

#         # ── Strategy 1: direct collect on ocr/ ───────────────────────────────
#         t = collect_ocr_text(ocr_dir)

#         # ── Strategy 2: look inside bundle subdirs (e.g. ocr/my_doc_pdf/) ────
#         if not t:
#             for sub in sorted(ocr_dir.iterdir()):
#                 if sub.is_dir():
#                     t = collect_ocr_text(sub)
#                     if t:
#                         break

#         # ── Strategy 3: rglob for any ocr_result.json under ocr/ ─────────────
#         if not t:
#             for ocr_json in ocr_dir.rglob("ocr_result.json"):
#                 try:
#                     data = load_json(ocr_json)
#                     if data and isinstance(data.get("pages", []), list):
#                         page_texts = []
#                         for page in data["pages"]:
#                             md = page.get("markdown", "").strip()
#                             if md:
#                                 page_texts.append(
#                                     f"--- Document JSON Page {page.get('index', 0)} ---\n{clean_markdown(md)}"
#                                 )
#                         if page_texts:
#                             t = "\n\n".join(page_texts)
#                             break
#                 except Exception:
#                     continue

#         # ── Strategy 4: rglob for any *.md files under ocr/ ──────────────────
#         if not t:
#             md_files = sorted(ocr_dir.rglob("*.md"))
#             if md_files:
#                 page_texts = []
#                 for md_file in md_files:
#                     try:
#                         content = md_file.read_text(encoding="utf-8").strip()
#                         if content:
#                             page_texts.append(f"--- {md_file.name} ---\n{content}")
#                     except Exception:
#                         continue
#                 t = "\n\n".join(page_texts)

#         if t:
#             texts.append(f"=== Document: {doc.get('original_name', doc['doc_id'])} ===\n{t}")

#     merged = "\n\n".join(texts)
#     if merged:
#         try:
#             combined_cache.parent.mkdir(parents=True, exist_ok=True)
#             combined_cache.write_text(merged, encoding="utf-8")
#         except Exception:
#             pass
#     return merged

# # ══════════════════════════════════════════════════════════════════════════════
# # VERIFICATION SYSTEM PROMPT
# # ══════════════════════════════════════════════════════════════════════════════

# VERIFICATION_SYSTEM_PROMPT = """
# You are an objective verifier comparing multiple-choice answers against an OCR-extracted document.
# Return a JSON array where each element corresponds to one input question ID and has the following keys:
# - id: (string) the question ID from the input
# - verification_status: one of ["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"]
# - confidence: numeric 0-100 estimating certainty of the verification
# - evidence_quote: short quote (<=250 chars) from the OCR that justifies the verdict, or "" if none
# - evidence_page: page identifier (e.g., "page_0003.md" or "Document JSON Page 2") where evidence was found, or "" if none
# - reasoning: plain-text explanation of how you reached the decision
# - suggested_answer: if the original selected answer seems wrong, suggest one of "A","B","C","D", or null

# Important:
# - Output only a single JSON array (or a fenced ```json block containing the array). Avoid extra commentary.
# - Be conservative: when evidence is partial, prefer PARTIALLY_SUPPORTED with a moderate confidence.
# - Use NOT_FOUND when no supporting text is present, not when contradictory evidence exists.
# """

# # ══════════════════════════════════════════════════════════════════════════════
# # SESSION FILESYSTEM HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def get_sessions_dir(username: str) -> Path:
#     return USER_DATA_DIR / username / "sessions"


# def create_new_session(username: str) -> tuple[str, Path]:
#     ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
#     sess_dir = get_sessions_dir(username) / ts
#     for sub in ("inputs", "documents", "processing", "outputs", "logs"):
#         (sess_dir / sub).mkdir(parents=True, exist_ok=True)
#     meta = {
#         "session_id":  ts,
#         "username":    username,
#         "created_at":  datetime.utcnow().isoformat() + "Z",
#         "status":      "created",
#         "doc_count":   0,
#         "company":     "",
#         "answer_mode": "",
#     }
#     (sess_dir / "metadata.json").write_text(
#         json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return ts, sess_dir


# def list_user_sessions(username: str) -> list[dict]:
#     """Return list of session metadata dicts, newest first."""
#     sessions_dir = get_sessions_dir(username)
#     if not sessions_dir.exists():
#         return []
#     result = []
#     for p in sorted(sessions_dir.iterdir(), reverse=True):
#         if not p.is_dir():
#             continue
#         meta_file = p / "metadata.json"
#         if meta_file.exists():
#             try:
#                 m = json.loads(meta_file.read_text(encoding="utf-8"))
#                 result.append(m)
#             except Exception:
#                 result.append({"session_id": p.name, "created_at": p.name})
#         else:
#             result.append({"session_id": p.name, "created_at": p.name})
#     return result


# def get_session_path(username: str, session_id: str) -> Path:
#     return get_sessions_dir(username) / session_id


# def update_session_meta(sess_dir: Path, updates: dict):
#     meta_file = sess_dir / "metadata.json"
#     try:
#         meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
#     except Exception:
#         meta = {}
#     meta.update(updates)
#     meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# def add_document_to_session(sess_dir: Path, file_bytes: bytes, filename: str) -> Path:
#     """
#     Save an uploaded file into the next available doc_XXX slot.
#     Returns the doc directory.
#     Layout:
#       session/documents/doc_001/original/<filename>
#       session/documents/doc_001/ocr/        (populated after OCR)
#       session/documents/doc_001/metadata.json
#     """
#     docs_dir = sess_dir / "documents"
#     existing = sorted([d for d in docs_dir.iterdir() if d.is_dir() and d.name.startswith("doc_")])
#     next_idx  = len(existing) + 1
#     doc_dir   = docs_dir / f"doc_{next_idx:03d}"
#     orig_dir  = doc_dir / "original"
#     orig_dir.mkdir(parents=True, exist_ok=True)
#     (doc_dir / "ocr").mkdir(parents=True, exist_ok=True)

#     safe_fname = safe_name(filename)
#     out_path   = orig_dir / safe_fname
#     out_path.write_bytes(file_bytes)

#     doc_meta = {
#         "doc_id":        f"doc_{next_idx:03d}",
#         "original_name": filename,
#         "filename":      safe_fname,
#         "size":          len(file_bytes),
#         "uploaded_at":   datetime.utcnow().isoformat() + "Z",
#         "ocr_status":    "pending",
#     }
#     (doc_dir / "metadata.json").write_text(
#         json.dumps(doc_meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return doc_dir


# def list_session_documents(sess_dir: Path) -> list[dict]:
#     """Return list of document metadata dicts for a session."""
#     docs_dir = sess_dir / "documents"
#     if not docs_dir.exists():
#         return []
#     result = []
#     for d in sorted(docs_dir.iterdir()):
#         if not d.is_dir() or not d.name.startswith("doc_"):
#             continue
#         mf = d / "metadata.json"
#         if mf.exists():
#             try:
#                 m = json.loads(mf.read_text(encoding="utf-8"))
#                 m["_path"] = str(d)
#                 result.append(m)
#             except Exception:
#                 result.append({"doc_id": d.name, "_path": str(d)})
#     return result


# def get_combined_ocr_text(sess_dir: Path) -> str:
#     """
#     Merge OCR text from all doc_XXX/ocr/ folders within a session.
#     Checks processing/combined_ocr.txt ONLY if non-empty (cache).
#     Always rebuilds if cache is missing or empty.
#     """
#     combined_cache = sess_dir / "processing" / "combined_ocr.txt"

#     # ── Only trust the cache if it is non-empty ──────────────────────────────
#     if combined_cache.exists():
#         try:
#             cached = combined_cache.read_text(encoding="utf-8").strip()
#             if cached:
#                 return cached
#             else:
#                 # Cache exists but is empty — delete it and rebuild
#                 combined_cache.unlink(missing_ok=True)
#         except Exception:
#             combined_cache.unlink(missing_ok=True)

#     texts = []
#     for doc in list_session_documents(sess_dir):
#         doc_path   = Path(doc["_path"])
#         ocr_dir    = doc_path / "ocr"
#         if not ocr_dir.exists():
#             continue

#         t = ""

#         # ── Strategy 1: direct collect on ocr/ ───────────────────────────────
#         t = collect_ocr_text(ocr_dir)

#         # ── Strategy 2: look inside bundle subdirs (e.g. ocr/my_doc_pdf/) ────
#         if not t:
#             for sub in sorted(ocr_dir.iterdir()):
#                 if sub.is_dir():
#                     t = collect_ocr_text(sub)
#                     if t:
#                         break

#         # ── Strategy 3: rglob for any ocr_result.json under ocr/ ─────────────
#         if not t:
#             for ocr_json in ocr_dir.rglob("ocr_result.json"):
#                 try:
#                     data = load_json(ocr_json)
#                     if data and isinstance(data.get("pages", []), list):
#                         page_texts = []
#                         for page in data["pages"]:
#                             md = page.get("markdown", "").strip()
#                             if md:
#                                 page_texts.append(
#                                     f"--- Document JSON Page {page.get('index', 0)} ---\n{clean_markdown(md)}"
#                                 )
#                         if page_texts:
#                             t = "\n\n".join(page_texts)
#                             break
#                 except Exception:
#                     continue

#         # ── Strategy 4: rglob for any *.md files under ocr/ ──────────────────
#         if not t:
#             md_files = sorted(ocr_dir.rglob("*.md"))
#             if md_files:
#                 page_texts = []
#                 for md_file in md_files:
#                     try:
#                         content = md_file.read_text(encoding="utf-8").strip()
#                         if content:
#                             page_texts.append(f"--- {md_file.name} ---\n{content}")
#                     except Exception:
#                         continue
#                 t = "\n\n".join(page_texts)

#         if t:
#             texts.append(f"=== Document: {doc.get('original_name', doc['doc_id'])} ===\n{t}")

#     merged = "\n\n".join(texts)
#     if merged:
#         try:
#             combined_cache.parent.mkdir(parents=True, exist_ok=True)
#             combined_cache.write_text(merged, encoding="utf-8")
#         except Exception:
#             pass
#     return merged

# # ══════════════════════════════════════════════════════════════════════════════
# # VERIFICATION SYSTEM PROMPT
# # ══════════════════════════════════════════════════════════════════════════════

# VERIFICATION_SYSTEM_PROMPT = """
# You are an objective verifier comparing multiple-choice answers against an OCR-extracted document.
# Return a JSON array where each element corresponds to one input question ID and has the following keys:
# - id: (string) the question ID from the input
# - verification_status: one of ["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"]
# - confidence: numeric 0-100 estimating certainty of the verification
# - evidence_quote: short quote (<=250 chars) from the OCR that justifies the verdict, or "" if none
# - evidence_page: page identifier (e.g., "page_0003.md" or "Document JSON Page 2") where evidence was found, or "" if none
# - reasoning: plain-text explanation of how you reached the decision
# - suggested_answer: if the original selected answer seems wrong, suggest one of "A","B","C","D", or null

# Important:
# - Output only a single JSON array (or a fenced ```json block containing the array). Avoid extra commentary.
# - Be conservative: when evidence is partial, prefer PARTIALLY_SUPPORTED with a moderate confidence.
# - Use NOT_FOUND when no supporting text is present, not when contradictory evidence exists.
# """

# # ══════════════════════════════════════════════════════════════════════════════
# # SESSION FILESYSTEM HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def get_sessions_dir(username: str) -> Path:
#     return USER_DATA_DIR / username / "sessions"


# def create_new_session(username: str) -> tuple[str, Path]:
#     ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
#     sess_dir = get_sessions_dir(username) / ts
#     for sub in ("inputs", "documents", "processing", "outputs", "logs"):
#         (sess_dir / sub).mkdir(parents=True, exist_ok=True)
#     meta = {
#         "session_id":  ts,
#         "username":    username,
#         "created_at":  datetime.utcnow().isoformat() + "Z",
#         "status":      "created",
#         "doc_count":   0,
#         "company":     "",
#         "answer_mode": "",
#     }
#     (sess_dir / "metadata.json").write_text(
#         json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return ts, sess_dir


# def list_user_sessions(username: str) -> list[dict]:
#     """Return list of session metadata dicts, newest first."""
#     sessions_dir = get_sessions_dir(username)
#     if not sessions_dir.exists():
#         return []
#     result = []
#     for p in sorted(sessions_dir.iterdir(), reverse=True):
#         if not p.is_dir():
#             continue
#         meta_file = p / "metadata.json"
#         if meta_file.exists():
#             try:
#                 m = json.loads(meta_file.read_text(encoding="utf-8"))
#                 result.append(m)
#             except Exception:
#                 result.append({"session_id": p.name, "created_at": p.name})
#         else:
#             result.append({"session_id": p.name, "created_at": p.name})
#     return result


# def get_session_path(username: str, session_id: str) -> Path:
#     return get_sessions_dir(username) / session_id


# def update_session_meta(sess_dir: Path, updates: dict):
#     meta_file = sess_dir / "metadata.json"
#     try:
#         meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
#     except Exception:
#         meta = {}
#     meta.update(updates)
#     meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# def add_document_to_session(sess_dir: Path, file_bytes: bytes, filename: str) -> Path:
#     """
#     Save an uploaded file into the next available doc_XXX slot.
#     Returns the doc directory.
#     Layout:
#       session/documents/doc_001/original/<filename>
#       session/documents/doc_001/ocr/        (populated after OCR)
#       session/documents/doc_001/metadata.json
#     """
#     docs_dir = sess_dir / "documents"
#     existing = sorted([d for d in docs_dir.iterdir() if d.is_dir() and d.name.startswith("doc_")])
#     next_idx  = len(existing) + 1
#     doc_dir   = docs_dir / f"doc_{next_idx:03d}"
#     orig_dir  = doc_dir / "original"
#     orig_dir.mkdir(parents=True, exist_ok=True)
#     (doc_dir / "ocr").mkdir(parents=True, exist_ok=True)

#     safe_fname = safe_name(filename)
#     out_path   = orig_dir / safe_fname
#     out_path.write_bytes(file_bytes)

#     doc_meta = {
#         "doc_id":        f"doc_{next_idx:03d}",
#         "original_name": filename,
#         "filename":      safe_fname,
#         "size":          len(file_bytes),
#         "uploaded_at":   datetime.utcnow().isoformat() + "Z",
#         "ocr_status":    "pending",
#     }
#     (doc_dir / "metadata.json").write_text(
#         json.dumps(doc_meta, indent=2, ensure_ascii=False), encoding="utf-8"
#     )
#     return doc_dir


# def list_session_documents(sess_dir: Path) -> list[dict]:
#     """Return list of document metadata dicts for a session."""
#     docs_dir = sess_dir / "documents"
#     if not docs_dir.exists():
#         return []
#     result = []
#     for d in sorted(docs_dir.iterdir()):
#         if not d.is_dir() or not d.name.startswith("doc_"):
#             continue
#         mf = d / "metadata.json"
#         if mf.exists():
#             try:
#                 m = json.loads(mf.read_text(encoding="utf-8"))
#                 m["_path"] = str(d)
#                 result.append(m)
#             except Exception:
#                 result.append({"doc_id": d.name, "_path": str(d)})
#     return result


# def get_combined_ocr_text(sess_dir: Path) -> str:
#     """
#     Merge OCR text from all doc_XXX/ocr/ folders within a session.
#     Checks processing/combined_ocr.txt ONLY if non-empty (cache).
#     Always rebuilds if cache is missing or empty.
#     """
#     combined_cache = sess_dir / "processing" / "combined_ocr.txt"

#     # ── Only trust the cache if it is non-empty ──────────────────────────────
#     if combined_cache.exists():
#         try:
#             cached = combined_cache.read_text(encoding="utf-8").strip()
#             if cached:
#                 return cached
#             else:
#                 # Cache exists but is empty — delete it and rebuild
#                 combined_cache.unlink(missing_ok=True)
#         except Exception:
#             combined_cache.unlink(missing_ok=True)

#     texts = []
#     for doc in list_session_documents(sess_dir):
#         doc_path   = Path(doc["_path"])
#         ocr_dir    = doc_path / "ocr"
#         if not ocr_dir.exists():
#             continue

#         t = ""

#         # ── Strategy 1: direct collect on ocr/ ───────────────────────────────
#         t = collect_ocr_text(ocr_dir)

#         # ── Strategy 2: look inside bundle subdirs (e.g. ocr/my_doc_pdf/) ────
#         if not t:
#             for sub in sorted(ocr_dir.iterdir()):
#                 if sub.is_dir():
#                     t = collect_ocr_text(sub)
#                     if t:
#                         break

#         # ── Strategy 3: rglob for any ocr_result.json under ocr/ ─────────────
#         if not t:
#             for ocr_json in ocr_dir.rglob("ocr_result.json"):
#                 try:
#                     data = load_json(ocr_json)
#                     if data and isinstance(data.get("pages", []), list):
#                         page_texts = []
#                         for page in data["pages"]:
#                             md = page.get("markdown", "").strip()
#                             if md:
#                                 page_texts.append(
#                                     f"--- Document JSON Page {page.get('index', 0)} ---\n{clean_markdown(md)}"
#                                 )
#                         if page_texts:
#                             t = "\n\n".join(page_texts)
#                             break
#                 except Exception:
#                     continue

#         # ── Strategy 4: rglob for any *.md files under ocr/ ──────────────────
#         if not t:
#             md_files = sorted(ocr_dir.rglob("*.md"))
#             if md_files:
#                 page_texts = []
#                 for md_file in md_files:
#                     try:
#                         content = md_file.read_text(encoding="utf-8").strip()
#                         if content:
#                             page_texts.append(f"--- {md_file.name} ---\n{content}")
#                     except Exception:
#                         continue
#                 t = "\n\n".join(page_texts)

#         if t:
#             texts.append(f"=== Document: {doc.get('original_name', doc['doc_id'])} ===\n{t}")

#     merged = "\n\n".join(texts)
#     if merged:
#         try:
#             combined_cache.parent.mkdir(parents=True, exist_ok=True)
#             combined_cache.write_text(merged, encoding="utf-8")
#         except Exception:
#             pass
#     return merged

# # ══════════════════════════════════════════════════════════════════════════════
# # LLM / API HELPERS  — stable pattern from sample_llm
# # ══════════════════════════════════════════════════════════════════════════════

# def _get_api_key() -> str:
#     if st.session_state.get("api_key", "").strip():
#         return st.session_state["api_key"].strip()
#     try:
#         from config.settings import settings
#         for attr in ("OPENROUTER_API_KEY", "openrouter_api_key", "api_key"):
#             val = getattr(settings, attr, None)
#             if val and str(val).strip():
#                 return str(val).strip()
#     except Exception:
#         pass
#     return os.getenv("OPENROUTER_API_KEY", "")


# def fetch_models(api_key: str) -> list[dict]:
#     def _fallback():
#         return [{"id": DEFAULT_MODEL, "name": DEFAULT_MODEL}]

#     if not api_key:
#         return _fallback()
#     try:
#         resp = requests.get(
#             OPENROUTER_MODELS_URL,
#             headers={
#                 "Authorization": f"Bearer {api_key}",
#                 "HTTP-Referer":  "https://pear-edtech.app",
#                 "X-Title":       "Pear EdTech Chatbot",
#             },
#             timeout=10,
#         )
#         resp.raise_for_status()
#         raw    = resp.json().get("data", []) or []
#         models = []
#         for m in raw:
#             mid  = m.get("id", "")
#             name = m.get("name", mid)
#             if not mid:
#                 continue
#             models.append({"id": mid, "name": name})
#         return models or _fallback()
#     except Exception:
#         return _fallback()


# def call_openrouter(
#     messages: list[dict],
#     model: str,
#     api_key: str,
#     temperature: float = 0.2,
#     max_tokens: int = 10000,        # ← raised from 4096; free models will cap themselves
# ) -> str:
#     """
#     Stable OpenRouter call — mirrors sample_llm pattern exactly.
#     Returns assistant content string (or an error string on failure).
#     """
#     effective_key = api_key or _get_api_key()
#     if not effective_key:
#         raise RuntimeError("Missing OpenRouter API key.")

#     payload = {
#         "model":       model,
#         "messages":    messages,
#         "temperature": float(temperature),
#         "max_tokens":  int(max_tokens),
#     }
#     headers = {
#         "Authorization": f"Bearer {effective_key}",
#         "Content-Type":  "application/json",
#         "HTTP-Referer":  "https://pear-edtech.app",
#         "X-Title":       "Pear EdTech Chatbot",
#     }
#     try:
#         r = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=120)
#         r.raise_for_status()
#         j = r.json()

#         # ── Primary path: standard OpenAI/OpenRouter chat completion shape ──
#         choices = j.get("choices", [])
#         if choices and isinstance(choices, list):
#             msg = (
#                 choices[0].get("message", {})
#                 if isinstance(choices[0], dict) else {}
#             )
#             content = msg.get("content", "") if isinstance(msg, dict) else ""
#             if content:
#                 return content

#         # ── Fallback: choices[0]["text"] (older shape) ──
#         if choices and isinstance(choices[0], dict) and "text" in choices[0]:
#             return choices[0]["text"]

#         # ── Last resort: return raw JSON string so parse_verification_json
#         #    still has something to work with ──
#         return str(j)

#     except Exception as e:
#         return f"[LLM Error: {e}]"

# # ══════════════════════════════════════════════════════════════════════════════
# # DATA HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def load_json(path: Path):
#     try:
#         return json.loads(path.read_text(encoding="utf-8"))
#     except Exception:
#         return None


# def save_json(p: Path, data):
#     p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# def safe_name(name: str) -> str:
#     if not name:
#         return "file"
#     return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


# def safe_image_name(raw_id: str, fallback: str) -> str:
#     base = re.split(r"[/\\]", raw_id)[-1]
#     base = re.sub(r'[\\/*?:"<>|]', "_", base).strip()
#     if not base:
#         base = fallback
#     if not re.search(r"\.(jpg|jpeg|png|gif|webp|bmp)$", base, re.IGNORECASE):
#         base += ".jpg"
#     return base


# def is_table_line(line: str) -> bool:
#     return line.strip().startswith("|") or bool(re.match(r"^\s*\|.*\|\s*$", line))


# def clean_markdown(md: str) -> str:
#     md = html.unescape(md)
#     md = re.sub(r"^\s*!\[[^\]]*\]\([^\)]+\)\s*$\n?", "", md, flags=re.M)
#     md = re.sub(r"data:image\/[a-zA-Z]+;base64,[A-Za-z0-9+/=\s]+", "", md)
#     md = re.sub(r"(\w)-\n(\w)", r"\1\2", md)
#     lines        = md.splitlines()
#     out_lines: List[str] = []
#     inside_table = False
#     for i, line in enumerate(lines):
#         stripped = line.strip()
#         if is_table_line(line):
#             inside_table = True
#             out_lines.append(line.rstrip())
#             continue
#         else:
#             if inside_table and stripped == "":
#                 inside_table = False
#         if re.match(r"^(#{1,6}\s)|^(\s*[-*+]\s)|^>\s|^---\s*$|^\s*\d+\.\s", line):
#             out_lines.append(line.rstrip())
#             continue
#         if stripped == "":
#             out_lines.append("")
#             continue
#         next_line = lines[i + 1] if i + 1 < len(lines) else ""
#         if (next_line.strip() == ""
#                 or re.match(r"^(#{1,6}\s)|^(\s*[-*+]\s)|^>\s|^\s*\d+\.\s", next_line)
#                 or is_table_line(next_line)):
#             out_lines.append(line.rstrip())
#         else:
#             out_lines.append(line.rstrip() + " ")
#     joined = "\n".join(out_lines)
#     joined = re.sub(r"[ \t]{2,}", " ", joined)
#     joined = re.sub(r"\s+([,.;:!?])", r"\1", joined)
#     joined = re.sub(r"\n{3,}", "\n\n", joined)
#     return joined.strip() + "\n"

# # ══════════════════════════════════════════════════════════════════════════════
# # OCR HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def collect_ocr_text(source_dir: Path, company_base: Path | None = None) -> str:
#     texts      = []
#     seen_paths: set = set()

#     # 1. ocr_result.json
#     json_path = source_dir / "ocr_result.json"
#     if json_path.exists():
#         data = load_json(json_path)
#         if data and isinstance(data.get("pages", []), list):
#             for page in data["pages"]:
#                 idx = page.get("index", 0)
#                 md  = page.get("markdown", "").strip()
#                 if md:
#                     texts.append(f"--- Document JSON Page {idx} ---\n{clean_markdown(md)}")
#             if texts:
#                 return "\n\n".join(texts)

#     # 2. pages/*.md
#     pages_dir = source_dir if source_dir.name == "pages" else source_dir / "pages"
#     if pages_dir.exists() and pages_dir.is_dir():
#         for md_file in sorted(pages_dir.glob("*.md")):
#             if md_file.resolve() in seen_paths:
#                 continue
#             try:
#                 content = md_file.read_text(encoding="utf-8").strip()
#                 if content:
#                     try:
#                         rel = md_file.relative_to(company_base) if company_base else md_file.name
#                     except ValueError:
#                         rel = md_file.name
#                     texts.append(f"--- Document: {rel} ---\n{content}")
#                     seen_paths.add(md_file.resolve())
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

import base64
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

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_BASE    = "https://api.mistral.ai/v1"
MISTRAL_HEADERS = {"Authorization": f"Bearer {MISTRAL_API_KEY}"} if MISTRAL_API_KEY else {}

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
    Returns the doc directory.
    Layout:
      session/documents/doc_001/original/<filename>
      session/documents/doc_001/ocr/        (populated after OCR)
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
    Checks processing/combined_ocr.txt first (cache).
    """
    combined_cache = sess_dir / "processing" / "combined_ocr.txt"
    if combined_cache.exists():
        try:
            cached = combined_cache.read_text(encoding="utf-8").strip()
            if cached:
                return cached
        except Exception:
            pass

    texts   = []
    docs    = list_session_documents(sess_dir)
    for doc in docs:
        doc_path = Path(doc["_path"])
        ocr_dir  = doc_path / "ocr"
        if not ocr_dir.exists():
            continue
        t = collect_ocr_text(ocr_dir)
        if t:
            texts.append(f"=== Document: {doc.get('original_name', doc['doc_id'])} ===\n{t}")

    merged = "\n\n".join(texts)
    if merged:
        combined_cache.write_text(merged, encoding="utf-8")
    return merged


# ══════════════════════════════════════════════════════════════════════════════
# VERIFICATION SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════════════

VERIFICATION_SYSTEM_PROMPT = """
You are an objective verifier comparing multiple-choice answers against an OCR-extracted document.

CRITICAL: Your entire response must be ONLY a valid JSON array. No preamble, no explanation, no markdown prose outside the array.
Start your response with [ and end with ].

Each element in the array must have:
- id: (string) the question ID from the input
- verification_status: one of ["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"]
- confidence: numeric 0-100
- evidence_quote: short quote (<=250 chars) from the OCR, or ""
- evidence_page: page identifier or ""
- reasoning: plain-text explanation
- suggested_answer: "A","B","C","D", or null

Rules:
- Output ONLY the JSON array. No other text before or after.
- PARTIALLY_SUPPORTED when evidence is partial.
- NOT_FOUND only when no supporting text exists.
- CONTRADICTED only when document explicitly contradicts the answer.
"""

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
            ctx     = m.get("context_length", 0) if isinstance(m, dict) else 0
            pricing = m.get("pricing", {}) if isinstance(m, dict) else {}
            models.append({"id": mid, "name": name, "ctx": ctx, "pricing": pricing})
        return models or _fallback()
    except Exception:
        return _fallback()


def call_openrouter(messages: list[dict], model: str, api_key: str,
                    temperature: float = 0.2, max_tokens: int = 2000) -> str:
    """
    Send a chat-style request to the OpenRouter API using robust parsing of the response.
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
        # Try the modern chat-completion shape first:
        choices = j.get("choices", [])
        if choices and isinstance(choices, list):
            first = choices[0]
            if isinstance(first, dict):
                # OpenRouter often nests assistant content under message.content
                msg = first.get("message", {}) or {}
                content = msg.get("content")
                if content:
                    return content
        # Fallback: some providers return choices[0]["text"]
        if choices and isinstance(choices[0], dict) and "text" in choices[0]:
            return choices[0]["text"]
        # Last resort: stringify the whole response
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
    lines     = md.splitlines()
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


def safe_name(name: str) -> str:
    if not name:
        return "file"
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def safe_image_name(raw_id: str, fallback: str) -> str:
    base = re.split(r"[/\\]", raw_id)[-1]
    base = re.sub(r'[\\/*?:"<>|]', "_", base).strip()
    if not base:
        base = fallback
    if not re.search(r"\.(jpg|jpeg|png|gif|webp|bmp)$", base, re.IGNORECASE):
        base += ".jpg"
    return base


def run_mistral_ocr(
    files: list,
    out_dir: Path,
    tmp_dir: Path,
    headers: dict,
    status_widget=None,
    progress_widget=None,
) -> list:
    """Run Mistral OCR. out_dir can be a session doc_XXX/ocr/ folder."""
    log_file = LOG_DIR / "bulk_ocr_log.json"

    def _load_log():
        if log_file.exists():
            try:
                return json.loads(log_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_log(log):
        try:
            log_file.write_text(json.dumps(log, indent=2), encoding="utf-8")
        except Exception:
            pass

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    log             = _load_log()
    created_bundles = []
    total           = len(files)

    for i, file_path in enumerate(files, start=1):
        file_path = Path(file_path)
        doc_key   = safe_name(file_path.name)

        if status_widget:
            status_widget.info(f"Processing {i}/{total}: {file_path.name}")

        if log.get(doc_key, {}).get("status") == "done":
            bundle = out_dir / safe_name(file_path.name.replace(".", "_"))
            if bundle.exists():
                created_bundles.append(bundle)
            if progress_widget:
                progress_widget.progress(i / total)
            continue

        doc_name   = safe_name(file_path.name.replace(".", "_"))
        out_root   = out_dir / doc_name
        pages_dir  = out_root / "pages"
        images_dir = out_root / "images"
        pages_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)

        try:
            with open(file_path, "rb") as f:
                r = requests.post(
                    f"{MISTRAL_BASE}/files",
                    headers=headers,
                    files={"file": (file_path.name, f)},
                    data={"purpose": "ocr"},
                    timeout=120,
                )
            if r.status_code != 200:
                raise RuntimeError(f"Upload failed ({r.status_code}): {r.text}")
            file_id = r.json()["id"]

            r = requests.get(
                f"{MISTRAL_BASE}/files/{file_id}/url",
                headers=headers, timeout=60,
            )
            if r.status_code != 200:
                raise RuntimeError(f"Signed URL failed ({r.status_code}): {r.text}")
            signed_url = r.json()["url"]

            payload = {
                "model":    "mistral-ocr-latest",
                "document": {"type": "document_url", "document_url": signed_url},
                "include_image_base64": True,
            }
            r = requests.post(
                f"{MISTRAL_BASE}/ocr",
                headers={**headers, "Content-Type": "application/json"},
                json=payload, timeout=300,
            )
            if r.status_code != 200:
                raise RuntimeError(f"OCR failed ({r.status_code}): {r.text}")

            result    = r.json()
            json_path = out_root / "ocr_result.json"
            json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

            pages       = result.get("pages", [])
            img_counter = 0
            for p in pages:
                idx     = p.get("index", 0)
                md      = p.get("markdown", "")
                cleaned = clean_markdown(md)
                (pages_dir / f"page_{idx:04d}.md").write_text(cleaned, encoding="utf-8")
                for img in p.get("images", []):
                    b64_data = img.get("image_base64")
                    if not b64_data:
                        continue
                    if "," in b64_data:
                        b64_data = b64_data.split(",", 1)[1]
                    try:
                        img_bytes = base64.b64decode(b64_data)
                    except Exception:
                        continue
                    raw_id   = img.get("id", "")
                    fallback = f"page{idx:04d}_img{img_counter:04d}.jpg"
                    img_name = safe_image_name(raw_id, fallback) if raw_id else fallback
                    img_counter += 1
                    (images_dir / img_name).write_bytes(img_bytes)

            log[doc_key] = {
                "status":      "done",
                "pages":       len(pages),
                "json_output": str(json_path),
                "time":        time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            _save_log(log)
            created_bundles.append(out_root)

        except Exception as e:
            log[doc_key] = {"status": "failed", "error": str(e)}
            _save_log(log)
            if status_widget:
                status_widget.error(f"❌ Failed: {file_path.name} — {e}")

        if progress_widget:
            progress_widget.progress(i / total)
        time.sleep(0.2)

    if status_widget and created_bundles:
        status_widget.success(f"✅ OCR complete — {len(created_bundles)} bundle(s) ready.")

    return created_bundles


def run_ocr_for_session_doc(doc_dir: Path, status_widget=None, progress_widget=None) -> bool:
    """
    Run Mistral OCR for a single session document.
    Writes results directly into doc_dir/ocr/.
    Updates doc_dir/metadata.json with ocr_status.
    Returns True on success.
    """
    orig_dir = doc_dir / "original"
    ocr_dir  = doc_dir / "ocr"
    ocr_dir.mkdir(parents=True, exist_ok=True)

    orig_files = list(orig_dir.glob("*"))
    if not orig_files:
        if status_widget:
            status_widget.warning(f"No files in {doc_dir.name}/original/")
        return False

    # Update doc metadata
    mf   = doc_dir / "metadata.json"
    meta = load_json(mf) or {}

    try:
        # Use a temporary directory for OCR intermediate files
        tmp = TMP_DIR / "ocr_tmp"
        tmp.mkdir(parents=True, exist_ok=True)

        # run_mistral_ocr outputs bundles; we want results in ocr_dir directly
        bundles = run_mistral_ocr(
            files=orig_files,
            out_dir=ocr_dir,
            tmp_dir=tmp,
            headers=MISTRAL_HEADERS,
            status_widget=status_widget,
            progress_widget=progress_widget,
        )

        # Invalidate combined cache so it gets rebuilt
        combined = doc_dir.parent.parent / "processing" / "combined_ocr.txt"
        if combined.exists():
            combined.unlink(missing_ok=True)

        meta["ocr_status"]    = "done"
        meta["ocr_completed"] = datetime.utcnow().isoformat() + "Z"
        meta["ocr_bundles"]   = [str(b.relative_to(doc_dir)) for b in bundles]
        mf.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        return True

    except Exception as e:
        meta["ocr_status"] = "failed"
        meta["ocr_error"]  = str(e)
        mf.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        if status_widget:
            status_widget.error(f"OCR failed for {doc_dir.name}: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# OCR TEXT COLLECTION
# ══════════════════════════════════════════════════════════════════════════════

def collect_ocr_text(source_dir: Path, company_base: Path | None = None) -> str:
    texts      = []
    seen_paths: set = set()

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


def ensure_ocr_for_company(company_dir: Path, data_dir: Path) -> Path | None:
    """
    Find a usable OCR source for company_dir.
    Priority:
      1. company_dir/ocr (if it has content)
      2. Any nested ocr/ folder inside company_dir
      3. Any ocr_result.json inside company_dir
      4. Any nested pages/ inside company_dir
      5. GLOBAL FALLBACK: search all of data_dir for ocr_result.json
    """
    ocr_dir = company_dir / "ocr"

    if ocr_dir.exists() and _has_ocr_content(ocr_dir):
        return ocr_dir

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

    for pages in sorted(company_dir.rglob("pages"), key=lambda p: len(p.parts), reverse=True):
        if pages.is_dir() and any(pages.glob("*.md")):
            try:
                ocr_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(pages, ocr_dir / "pages", dirs_exist_ok=True)
                if _has_ocr_content(ocr_dir):
                    return ocr_dir
            except Exception:
                return pages

    # Global fallback: search all of data_dir
    try:
        for j in sorted(data_dir.rglob("ocr_result.json")):
            try:
                j.relative_to(company_dir)
                continue  # inside company_dir → already handled
            except ValueError:
                pass

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
                return parent
    except Exception:
        pass

    return None


def get_ocr_text_from_data(company_dir: Path) -> tuple[str, Path | None]:
    """Fallback: look for OCR in DATA_DIR (mirrors sample_llm.py behaviour)."""
    try:
        ocr_source = ensure_ocr_for_company(company_dir, DATA_DIR)
        if ocr_source:
            text = collect_ocr_text(ocr_source, company_base=company_dir)
            return text or "", ocr_source
    except Exception:
        pass
    return "", None


# ...existing code...

# ── 2c. Build / preview merged OCR text ───────────────────────────────────────
with st.spinner("Merging OCR text from session documents…"):
    final_ocr_text            = get_combined_ocr_text(active_sess_dir)
    st.session_state.ocr_text = final_ocr_text or ""

# ── NEW: fall back to DATA_DIR discovery when session has no OCR yet ──────────
fallback_source: Path | None = None
if not st.session_state.ocr_text.strip():
    with st.spinner("No session OCR found — searching DATA_DIR for existing OCR…"):
        fb_text, fallback_source = get_ocr_text_from_data(DATA_DIR / company_name)
        if fb_text:
            st.session_state.ocr_text = fb_text

if not st.session_state.ocr_text.strip():
    st.warning(
        "⚠️ No OCR text available yet. Upload and OCR at least one document above, "
        "or verify results will be marked NOT_FOUND."
    )
else:
    char_count = len(st.session_state.ocr_text)
    if fallback_source:
        try:
            src_label = fallback_source.relative_to(DATA_DIR)
        except Exception:
            src_label = fallback_source
        st.info(
            f"ℹ️ No session OCR found — using existing OCR from `{src_label}` "
            f"({char_count:,} chars)."
        )
    else:
        st.success(
            f"✅ OCR ready — {char_count:,} chars from "
            f"{len(session_docs)} document(s)."
        )

with st.expander("👁️ Preview merged OCR text (first 3 000 chars)", expanded=False):
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
        st.error("No answers found.")
    else:
        inputs_dir = active_sess_dir / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        if not (inputs_dir / "answers.json").exists():
            save_json(inputs_dir / "answers.json", {
                "company":   company_name,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "mode":      answer_mode,
                "answers":   answers,
            })

        prompt_user = build_verification_prompt(answers, st.session_state.ocr_text, max_ocr_chars=14000)
        messages    = [
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
                    max_tokens=4096,  # safer limit; most free models cap here
                )
            elapsed = time.time() - t0
            progress.progress(80, text="Parsing response…")
            verifications = parse_verification_json(raw_reply)

            if verifications is None:
                st.warning("⚠️ LLM returned a non-JSON response. Marking answers as NOT_FOUND.")
                verifications = [
                    {"id": a["id"], "verification_status": "NOT_FOUND",
                     "confidence": 0, "evidence_quote": "", "evidence_page": "",
                     "reasoning": "LLM response unparsable.", "suggested_answer": None}
                    for a in answers
                ]

            # Fill in any missing question IDs
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
                "session_id":        active_sess_id,
                "source_file":       (st.session_state.answer_data or {}).get("source_file",""),
                "timestamp":         datetime.utcnow().isoformat() + "Z",
                "model":             st.session_state.model_id,
                "status":            "ok",
                "total_final_score": float(score_df["Final Score"].sum()),
                "total_max_score":   int(score_df["Max Score"].sum()),
                "total_raw_score":   int(score_df["Raw Score"].sum()),
                "pct_verified":      round(score_df["Final Score"].sum() / score_df["Max Score"].sum() * 100, 2)
                                     if score_df["Max Score"].sum() else 0,
                "verifications":     verifications,
                "answers":           answers,
                "scores":            score_df.to_dict(orient="records"),
                "raw_llm_reply":     raw_reply,
            }

            # Save to session outputs/
            outputs_dir = active_sess_dir / "outputs"
            outputs_dir.mkdir(parents=True, exist_ok=True)
            save_json(outputs_dir / "verification.json", result_payload)
            score_df.to_csv(outputs_dir / "scores.csv", index=False)
            (outputs_dir / "raw_llm_reply.txt").write_text(raw_reply or "", encoding="utf-8")

            update_session_meta(active_sess_dir, {
                "status":      "verified",
                "verified_at": datetime.utcnow().isoformat() + "Z",
                "pct_score":   result_payload["pct_verified"],
            })

            elapsed = time.time() - t0
            progress.progress(100, text=f"Done in {elapsed:.1f}s")
            st.success(f"✅ Verification complete in {elapsed:.1f}s — results saved to session.")

        except Exception as e:
            err_info = {
                "session_id":    active_sess_id,
                "timestamp":     datetime.utcnow().isoformat() + "Z",
                "model":         st.session_state.model_id,
                "status":        "error",
                "error":         str(e),
                "raw_llm_reply": raw_reply,
            }
            try:
                logs_dir = active_sess_dir / "logs"
                logs_dir.mkdir(parents=True, exist_ok=True)
                save_json(logs_dir / "error.json", err_info)
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
        pillar_filter = st.radio("Filter by pillar",
                                 ["All","Environmental","Social","Governance"], horizontal=True)
        status_filter = st.multiselect(
            "Filter by verification status",
            ["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"],
            default=["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"],
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
            "ID","Pillar","Question","Selected","Selected Text",
            "Raw Score","Status","Confidence","Multiplier","Final Score","Max Score","Reasoning",
        ]
        st.dataframe(df[display_cols], use_container_width=True, height=600)
        st.subheader("Pillar Totals")
        pillar_summary = df.groupby("Pillar").agg(
            Questions=("ID","count"),
            Raw_Score=("Raw Score","sum"),
            Final_Score=("Final Score","sum"),
            Max_Score=("Max Score","sum"),
            Avg_Confidence=("Confidence","mean"),
        ).reset_index()
        pillar_summary["Score_%"] = (pillar_summary["Final_Score"] / pillar_summary["Max Score"] * 100).round(1)
        st.dataframe(pillar_summary, use_container_width=True)

    with tab_raw:
        st.caption("Raw JSON response from LLM")
        st.code(st.session_state.raw_llm_reply, language="json")

    with tab_download:
        st.subheader("Download Results")
        result_json = {
            "company":           company_name,
            "session_id":        active_sess_id,
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
            file_name=f"{company_name}_{active_sess_id}_verification.json",
            mime="application/json",
        )
        st.download_button(
            "📥 Download Score Table CSV",
            data=df.to_csv(index=False),
            file_name=f"{company_name}_{active_sess_id}_scores.csv",
            mime="text/csv",
        )

st.stop()
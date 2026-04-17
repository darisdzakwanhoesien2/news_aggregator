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
from streamlit_compat import get_query_params

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
    docs_dir = sess_dir / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)  # ← ensure it exists before iterdir()
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
        "ocr_status":    "pending",  # always start as pending
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
    combined_cache = sess_dir / "processing" / "combined_ocr.txt"
    if combined_cache.exists():
        try:
            cached = combined_cache.read_text(encoding="utf-8").strip()
            if cached:
                return cached
        except Exception:
            pass

    texts = []
    docs  = list_session_documents(sess_dir)
    for doc in docs:
        doc_path = Path(doc["_path"])
        ocr_dir  = doc_path / "ocr"
        if not ocr_dir.exists():
            continue

        collected = ""

        # Strategy 1: bundle subdirs written by run_mistral_ocr
        # e.g. ocr_dir/<safe_doc_name>/ocr_result.json  or  ocr_dir/<safe_doc_name>/pages/*.md
        try:
            bundle_dirs = [d for d in ocr_dir.iterdir() if d.is_dir()]
        except Exception:
            bundle_dirs = []

        if bundle_dirs:
            bundle_texts = []
            for bundle in sorted(bundle_dirs):
                t = collect_ocr_text(bundle)
                if t:
                    bundle_texts.append(t)
            collected = "\n\n".join(bundle_texts)

        # Strategy 2: results written directly into ocr_dir (flat layout)
        if not collected:
            collected = collect_ocr_text(ocr_dir)

        # Strategy 3: deep rglob for any ocr_result.json anywhere under ocr_dir
        if not collected:
            for j in sorted(ocr_dir.rglob("ocr_result.json")):
                try:
                    raw = load_json(j)
                    if raw and isinstance(raw.get("pages"), list):
                        page_texts = []
                        for page in raw["pages"]:
                            md = page.get("markdown", "").strip()
                            if md:
                                page_texts.append(
                                    f"--- Page {page.get('index', 0)} ---\n{clean_markdown(md)}"
                                )
                        if page_texts:
                            collected = "\n\n".join(page_texts)
                            break
                except Exception:
                    continue

        # Strategy 4: rglob for any *.md files under ocr_dir
        if not collected:
            md_files = sorted(ocr_dir.rglob("*.md"))
            if md_files:
                md_texts = []
                for mf in md_files:
                    try:
                        content = mf.read_text(encoding="utf-8").strip()
                        if content:
                            md_texts.append(f"--- {mf.name} ---\n{content}")
                    except Exception:
                        continue
                collected = "\n\n".join(md_texts)

        if collected:
            texts.append(
                f"=== Document: {doc.get('original_name', doc.get('doc_id','?'))} ===\n{collected}"
            )

    merged = "\n\n".join(texts)
    if merged:
        try:
            combined_cache.parent.mkdir(parents=True, exist_ok=True)
            combined_cache.write_text(merged, encoding="utf-8")
        except Exception:
            pass
    return merged


# ══════════════════════════════════════════════════════════════════════════════
# VERIFICATION SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════════════

VERIFICATION_SYSTEM_PROMPT = """You are a JSON-only verification API. You MUST output ONLY a raw JSON array.
NEVER output any explanation, markdown, preamble, or prose.
Your response MUST start with [ and end with ].
Any response that is not a valid JSON array is a failure."""

# ══════════════════════════════════════════════════════════════════════════════
# LLM / API HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def run_verification_in_batches(
    answers: list[dict],
    ocr_text: str,
    model: str,
    api_key: str,
    batch_size: int = 5,
    status_widget=None,
) -> tuple[list[dict], str]:
    """
    Split answers into batches to avoid token truncation.
    Returns (all_verifications, combined_raw_reply).
    """
    all_verifications = []
    all_raw_replies   = []
    batches = [answers[i:i+batch_size] for i in range(0, len(answers), batch_size)]

    for batch_idx, batch in enumerate(batches):
        if status_widget:
            status_widget.info(
                f"🔄 Verifying batch {batch_idx+1}/{len(batches)} "
                f"({len(batch)} questions)…"
            )

        prompt_user = build_verification_prompt(batch, ocr_text, max_ocr_chars=12000)
        messages = [
            {"role": "system", "content": VERIFICATION_SYSTEM_PROMPT},
            {"role": "user",   "content": prompt_user},
        ]

        raw_reply = call_openrouter(
            messages=messages,
            model=model,
            api_key=api_key,
            temperature=0.0,   # ✅ 0 temp = more deterministic, less creative prose
            max_tokens=2048,   # ✅ smaller per batch = less likely to truncate
        )
        all_raw_replies.append(f"--- Batch {batch_idx+1} ---\n{raw_reply}")

        verifications = parse_verification_json(raw_reply)
        if verifications:
            all_verifications.extend(verifications)
        else:
            # Mark batch as NOT_FOUND if parse fails
            if status_widget:
                status_widget.warning(
                    f"⚠️ Batch {batch_idx+1} returned non-JSON. Raw reply:\n```\n{raw_reply[:500]}\n```"
                )
            for a in batch:
                all_verifications.append({
                    "id": a["id"],
                    "verification_status": "NOT_FOUND",
                    "confidence": 0,
                    "evidence_quote": "",
                    "evidence_page": "",
                    "reasoning": f"LLM returned non-JSON for this batch. Raw: {raw_reply[:200]}",
                    "suggested_answer": None,
                })

        time.sleep(1.0)  # ✅ rate limit buffer between batches

    return all_verifications, "\n\n".join(all_raw_replies)

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

        # ✅ FIX: Only skip if log says "done" AND the bundle actually exists with real files
        if log.get(doc_key, {}).get("status") == "done":
            bundle = out_dir / safe_name(file_path.name.replace(".", "_"))
            bundle_has_files = (
                bundle.exists()
                and any(f.is_file() for f in bundle.rglob("*"))
            )
            if bundle_has_files:
                created_bundles.append(bundle)
                if progress_widget:
                    progress_widget.progress(i / total)
                continue
            else:
                # ✅ Stale log entry — clear it and re-run OCR
                if status_widget:
                    status_widget.warning(
                        f"⚠️ Log says done but bundle missing for {file_path.name}. Re-running OCR."
                    )
                log.pop(doc_key, None)
                _save_log(log)

        doc_name   = safe_name(file_path.name.replace(".", "_"))
        out_root   = out_dir / doc_name
        pages_dir  = out_root / "pages"
        images_dir = out_root / "images"
        pages_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)

        try:
            # ── Upload ──────────────────────────────────────────────────────
            if status_widget:
                status_widget.info(f"📤 Uploading {file_path.name} to Mistral…")
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
            if status_widget:
                status_widget.info(f"✅ Uploaded. file_id={file_id}")

            # ── Signed URL ──────────────────────────────────────────────────
            r = requests.get(
                f"{MISTRAL_BASE}/files/{file_id}/url",
                headers=headers, timeout=60,
            )
            if r.status_code != 200:
                raise RuntimeError(f"Signed URL failed ({r.status_code}): {r.text}")
            signed_url = r.json()["url"]

            # ── OCR ─────────────────────────────────────────────────────────
            if status_widget:
                status_widget.info(f"🔍 Running OCR on {file_path.name}…")
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
            json_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            pages       = result.get("pages", [])
            if status_widget:
                status_widget.info(f"📄 OCR returned {len(pages)} page(s). Saving…")

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
                # ✅ Show full error detail so we can see exactly what API returned
                status_widget.error(f"❌ Failed: {file_path.name}\n\nReason: {e}")

        if progress_widget:
            progress_widget.progress(i / total)
        time.sleep(0.2)

    if status_widget and created_bundles:
        status_widget.success(f"✅ OCR complete — {len(created_bundles)} bundle(s) ready.")

    return created_bundles


def run_ocr_for_session_doc(doc_dir: Path, status_widget=None, progress_widget=None) -> bool:
    orig_dir = doc_dir / "original"
    ocr_dir  = doc_dir / "ocr"
    ocr_dir.mkdir(parents=True, exist_ok=True)

    # ✅ FIX 1: Only include actual files, not directories
    orig_files = [f for f in orig_dir.glob("*") if f.is_file()]
    
    if not orig_files:
        if status_widget:
            status_widget.warning(f"No files in {doc_dir.name}/original/")
        return False

    if not MISTRAL_API_KEY:
        if status_widget:
            status_widget.error("MISTRAL_API_KEY is not set in .env")
        return False

    mf   = doc_dir / "metadata.json"
    meta = load_json(mf) or {}

    meta["ocr_status"] = "running"
    mf.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        tmp = TMP_DIR / "ocr_tmp"
        tmp.mkdir(parents=True, exist_ok=True)

        bundles = run_mistral_ocr(
            files=orig_files,
            out_dir=ocr_dir,
            tmp_dir=tmp,
            headers=MISTRAL_HEADERS,
            status_widget=status_widget,
            progress_widget=progress_widget,
        )

        # ✅ FIX 2: Also check for images as valid output
        valid_bundles = []
        for b in bundles:
            ocr_json = b / "ocr_result.json"
            pages    = list((b / "pages").glob("*.md")) if (b / "pages").exists() else []
            images   = list((b / "images").glob("*")) if (b / "images").exists() else []
            if ocr_json.exists() or pages or images:
                valid_bundles.append(b)

        if not valid_bundles:
            # ✅ FIX 3: Show what was actually written to help debug
            all_written = list(ocr_dir.rglob("*"))
            raise RuntimeError(
                f"OCR ran but produced no output files in {ocr_dir}. "
                f"Files found: {[str(f) for f in all_written[:10]]}. "
                "Check MISTRAL_API_KEY and Mistral API quota."
            )

        combined = doc_dir.parent.parent / "processing" / "combined_ocr.txt"
        combined.unlink(missing_ok=True)

        meta["ocr_status"]    = "done"
        meta["ocr_completed"] = datetime.utcnow().isoformat() + "Z"
        meta["ocr_bundles"]   = [str(b.relative_to(doc_dir)) for b in valid_bundles]
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


# ══════════════════════════════════════════════════════════════════════════════
# SCORING & VERIFICATION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def chunk_text(text: str, size: int = 1200, overlap: int = 250) -> list[str]:
    if not text:
        return []
    chunks: list[str] = []
    i    = 0
    L    = len(text)
    step = max(1, size - overlap)
    while i < L:
        chunks.append(text[i: min(i + size, L)])
        i += step
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
        qs     = " ".join([a.get("question", "") + " " + a.get("selected_text", "") for a in answers])
        chunks = chunk_text(ocr_text, size=1200, overlap=250)
        top    = retrieve_relevant_chunks(qs, chunks, top_k=12)
        ocr_snippet = "\n\n---\n\n".join(top)
        if len(ocr_snippet) > max_ocr_chars:
            ocr_snippet = ocr_snippet[:max_ocr_chars]
        ocr_snippet += f"\n\n[... truncated; original: {len(ocr_text)} chars ...]"

    qa_block = []
    for a in answers:
        qa_block.append(
            f"ID: {a.get('id')}\n"
            f"Pillar: {a.get('pillar', '')}\n"
            f"Question: {a.get('question', '')}\n"
            f"Selected Answer: {a.get('selected', '')} — {a.get('selected_text', '')}\n"
        )

    # ✅ Make the required output format crystal clear in the user prompt too
    example = '[{"id":"q1","verification_status":"SUPPORTED","confidence":85,"evidence_quote":"...","evidence_page":"p1","reasoning":"...","suggested_answer":"A"}]'
    return (
        f"OCR DOCUMENT TEXT:\n{ocr_snippet}\n\n"
        f"===\n\n"
        f"TASK: Verify each MCQ answer below. Return ONLY a JSON array.\n"
        f"REQUIRED FORMAT EXAMPLE: {example}\n\n"
        f"verification_status must be one of: SUPPORTED, PARTIALLY_SUPPORTED, NOT_FOUND, CONTRADICTED\n\n"
        f"MCQ ANSWERS ({len(answers)} questions):\n{'---'.join(qa_block)}\n\n"
        f"OUTPUT ONLY THE JSON ARRAY STARTING WITH [ AND ENDING WITH ]:"
    )


def parse_verification_json(raw: str) -> list[dict] | None:
    """
    Robustly extract a JSON array from LLM reply.

    Tries:
      1. Direct json.loads of whole string
      2. Fenced ```json ... ``` blocks containing an array
      3. Finds the first balanced '[' ... ']' substring that parses as a list
      4. As last resort attempts to clean trailing commas and parse again

    Returns list[dict] on success, else None.
    """
    if not raw or not raw.strip():
        return None

    # 1) direct parse
    try:
        data = json.loads(raw.strip())
        if isinstance(data, list):
            return data
    except Exception:
        pass

    # 2) fenced code block with JSON
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass

    # 3) attempt to find the first balanced JSON array by scanning for '['
    decoder = json.JSONDecoder()
    raw_len = len(raw)
    for i, ch in enumerate(raw):
        if ch != "[":
            continue
        try:
            # raw_decode expects the string to start at index 0, so give substring
            candidate, end = decoder.raw_decode(raw[i:])
            if isinstance(candidate, list):
                return candidate
        except Exception:
            continue

    # 4) fallback: try to salvage by removing trailing commas before ] or }
    cleaned = re.sub(r",\s*(\]|})", r"\1", raw)
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
    except Exception:
        pass

    # nothing parseable found
    return None


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
        mult      = STATUS_MULTIPLIER.get(status, 0.5)
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
            "Multiplier":       mult,
            "Final Score":      round(raw_score * mult, 2),
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
        f'<span style="background:{color};color:white;'
        f'padding:2px 8px;border-radius:8px;font-size:0.75rem">{pillar}</span>'
    )


def score_badge(score: float, max_score: float) -> str:
    pct   = score / max_score if max_score > 0 else 0
    color = "#2e7d32" if pct >= 0.8 else "#f57c00" if pct >= 0.5 else "#c62828"
    return (
        f'<span style="background:{color};color:white;'
        f'padding:2px 8px;border-radius:8px;font-size:0.85rem">{score:.1f}/{max_score}</span>'
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
# RESOLVE CURRENT USER
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_user() -> str | None:
    u = st.session_state.get("user")
    if u:
        return u
    try:
        params = get_query_params()
        if "user" in params and params["user"]:
            st.session_state["user"] = params["user"][0]
            return st.session_state["user"]
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE DEFAULTS
# ══════════════════════════════════════════════════════════════════════════════

_DEFAULTS = {
    "api_key":             os.getenv("OPENROUTER_API_KEY", ""),
    "model_id":            DEFAULT_MODEL,
    "verification":        None,
    "score_df":            None,
    "raw_llm_reply":       "",
    "ocr_text":            "",
    "answer_data":         None,
    "active_session_id":   None,
    "active_session_path": None,
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
        model_ids     = [m["id"] for m in models]
        default_idx   = next((i for i, mid in enumerate(model_ids) if DEFAULT_MODEL in mid), 0)
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

current_user = _resolve_user()

# ── Session Management ─────────────────────────────────────────────────────────
st.header("📁 Session Management")

if not current_user:
    st.warning("⚠️ You are not logged in. Session history will not be persisted.")
    current_user = "anonymous"

col_new, col_pick = st.columns([1, 2])

with col_new:
    if st.button("➕ New Session", type="primary"):
        sid, spath = create_new_session(current_user)
        st.session_state.active_session_id   = sid
        st.session_state.active_session_path = str(spath)
        st.session_state.verification  = None
        st.session_state.score_df      = None
        st.session_state.raw_llm_reply = ""
        st.session_state.ocr_text      = ""
        st.session_state.answer_data   = None
        st.success(f"✅ New session created: `{sid}`")
        st.rerun()

with col_pick:
    past_sessions = list_user_sessions(current_user)
    if past_sessions:
        session_labels = [
            f"{s['session_id']}  ·  {s.get('company','—')}  ·  {s.get('status','?')}"
            for s in past_sessions
        ]
        chosen_label = st.selectbox(
            "Or load an existing session",
            options=["— select —"] + session_labels,
            key="session_picker",
        )
        if chosen_label != "— select —":
            idx    = session_labels.index(chosen_label)
            picked = past_sessions[idx]
            if st.button("📂 Load selected session"):
                st.session_state.active_session_id   = picked["session_id"]
                st.session_state.active_session_path = str(
                    get_session_path(current_user, picked["session_id"])
                )
                out_f = (
                    get_session_path(current_user, picked["session_id"])
                    / "outputs" / "verification.json"
                )
                if out_f.exists():
                    saved = load_json(out_f) or {}
                    st.session_state.verification  = saved.get("verifications")
                    st.session_state.raw_llm_reply = saved.get("raw_llm_reply", "")
                    answers_saved = saved.get("answers", [])
                    if answers_saved and st.session_state.verification:
                        st.session_state.score_df = compute_scores(
                            answers_saved, st.session_state.verification
                        )
                    st.session_state.answer_data = {"answers": answers_saved}
                else:
                    st.session_state.verification  = None
                    st.session_state.score_df      = None
                    st.session_state.raw_llm_reply = ""
                st.success(f"Session `{picked['session_id']}` loaded.")
                st.rerun()
    else:
        st.info("No previous sessions found. Click **➕ New Session** to begin.")

if not st.session_state.active_session_id:
    st.info("👆 Create or load a session above to continue.")
    st.stop()

active_sess_dir = Path(st.session_state.active_session_path)
active_sess_id  = st.session_state.active_session_id
sess_meta       = load_json(active_sess_dir / "metadata.json") or {}

st.info(
    f"**Active session:** `{active_sess_id}` · "
    f"Company: `{sess_meta.get('company','—')}` · "
    f"Status: `{sess_meta.get('status','created')}`"
)

# ── Step 1 ─────────────────────────────────────────────────────────────────────
st.header("Step 1 — Company & Answer Source")

companies = sorted([
    p.name for p in DATA_DIR.iterdir()
    if p.is_dir() and not p.name.startswith(".")
    and p.name not in ("thesis_pdf", "thesis_dataset")
])
if not companies:
    st.error("No company folders found in the data directory.")
    st.stop()

col1, col2 = st.columns(2)
with col1:
    company_name = st.selectbox("Company", options=companies)
with col2:
    answer_mode = st.radio("Answer source", ["Load from file", "Use ESG question set"], index=1)

company_dir = DATA_DIR / company_name

if sess_meta.get("company") != company_name:
    update_session_meta(active_sess_dir, {"company": company_name, "answer_mode": answer_mode})

answers: list[dict] = []
if st.session_state.get("answer_data"):
    answers = st.session_state.answer_data.get("answers", []) or []

if answer_mode == "Load from file":
    candidate_dir = company_dir / "mcq_answers"
    answer_files  = (
        sorted(candidate_dir.glob("*.json"))
        if candidate_dir.exists()
        else sorted(company_dir.glob("*.json"))
    )
    if not answer_files:
        st.warning(f"No MCQ answer files found for **{company_name}**.")
    else:
        selected_file = st.selectbox(
            "MCQ Answer File", options=answer_files, format_func=lambda p: p.name
        )
        if selected_file:
            answer_data = load_json(selected_file)
            if not answer_data:
                st.error(f"Could not load {selected_file.name}")
            else:
                answer_data = answer_data if isinstance(answer_data, dict) else {"answers": []}
                answer_data["source_file"] = selected_file.name
                st.session_state.answer_data = answer_data
                answers = answer_data.get("answers", [])

elif answer_mode == "Use ESG question set":
    if not ESG_MCQ:
        st.error("ESG question set not found. Place a valid data/esg_mcq.json file.")
    else:
        st.markdown(f"Using ESG question set ({len(ESG_MCQ)} questions). Fill answers below.")
        with st.form("esg_answers_form", clear_on_submit=False):
            esg_answers = []
            for q in ESG_MCQ:
                qid           = str(q.get("id") or q.get("ID") or q.get("qid") or f"q_{len(esg_answers)+1}")
                pillar        = q.get("pillar", q.get("Pillar", ""))
                question_text = q.get("question", q.get("text", ""))
                raw_choices   = q.get("choices") or q.get("options") or []
                opts = []
                if isinstance(raw_choices, dict):
                    for k, v in raw_choices.items():
                        opts.append((str(k).upper(), str(v)))
                elif isinstance(raw_choices, list):
                    for i, item in enumerate(raw_choices):
                        opts.append((["A","B","C","D","E"][i] if i < 5 else str(i+1), str(item)))
                else:
                    opts = [("A","A"),("B","B"),("C","C"),("D","D")]

                choice_labels   = [f"{l}: {t}" for l, t in opts]
                sel             = st.selectbox(
                    f"{qid} — {pillar}\n{question_text}",
                    options=choice_labels, key=f"esg_sel_{qid}"
                )
                selected_letter = sel.split(":", 1)[0].strip()
                opt_map         = {l: t for l, t in opts}
                selected_text   = st.text_input(
                    f"Selected text for {qid} (optional)",
                    value=opt_map.get(selected_letter, ""),
                    key=f"esg_text_{qid}",
                )
                esg_answers.append({
                    "id": qid, "pillar": pillar, "question": question_text,
                    "selected": selected_letter, "selected_text": selected_text,
                })
            submitted = st.form_submit_button("Use these answers")
        if submitted:
            answers = esg_answers
            st.session_state.answer_data = {
                "company":     company_name,
                "timestamp":   datetime.utcnow().isoformat() + "Z",
                "mode":        "esg_mcq_interactive",
                "source_file": "interactive_esg",
                "answers":     answers,
            }
            inputs_dir = active_sess_dir / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)
            save_json(inputs_dir / "answers.json", st.session_state.answer_data)
            st.success(f"Collected {len(answers)} answers — saved to session inputs.")

if not answers:
    st.stop()

# ── Step 2 ─────────────────────────────────────────────────────────────────────
st.header("Step 2 — Upload & OCR Documents")
st.caption(
    "Each file you upload becomes an individual document in this session. "
    "All documents are OCR-processed separately, then merged for verification."
)

# ── 2a. Upload documents into session ─────────────────────────────────────────
uploads = st.file_uploader(
    "📎 Attach supporting document(s) for this session",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files=True,
    key="session_doc_uploader",
)

if uploads:
    # Build a set of filenames already saved in this session
    already_saved = {
        doc.get("original_name")
        for doc in list_session_documents(active_sess_dir)
    }

    newly_saved = []
    skipped     = []
    for uf in uploads:
        if uf.name in already_saved:
            skipped.append(uf.name)
            continue
        doc_dir = add_document_to_session(active_sess_dir, uf.getbuffer(), uf.name)
        newly_saved.append(doc_dir)
        already_saved.add(uf.name)   # prevent duplicate within the same upload batch

    if newly_saved:
        update_session_meta(active_sess_dir, {
            "doc_count": len(list_session_documents(active_sess_dir)),
            "status":    "documents_uploaded",
        })
        st.success(f"✅ Saved {len(newly_saved)} new document(s) to session.")
    if skipped:
        st.info(f"ℹ️ Skipped {len(skipped)} already-saved file(s): {', '.join(skipped)}")

# ── 2b. Show documents in this session and OCR controls ───────────────────────
session_docs = list_session_documents(active_sess_dir)

if session_docs:
    st.markdown(f"**Documents in this session ({len(session_docs)}):**")
    for doc in session_docs:
        doc_path   = Path(doc["_path"])
        ocr_dir    = doc_path / "ocr"
        ocr_status = doc.get("ocr_status", "pending")

        # Auto-correct: if metadata says "done" but ocr dir is empty → reset to pending
        if ocr_status == "done":
            ocr_files = list(ocr_dir.rglob("*")) if ocr_dir.exists() else []
            actual_files = [f for f in ocr_files if f.is_file()]
            if not actual_files:
                ocr_status = "pending"
                update_session_meta(doc_path, {"ocr_status": "pending"})

        icon       = "✅" if ocr_status == "done" else "⏳" if ocr_status == "pending" else ("❌" if ocr_status == "failed" else "🔄")
        col_info, col_btn = st.columns([4, 1])
        with col_info:
            st.markdown(
                f"{icon} **{doc['doc_id']}** — `{doc.get('original_name','?')}` "
                f"({doc.get('size',0):,} bytes) · OCR: `{ocr_status}`"
            )
            if doc.get("ocr_error"):
                st.caption(f"⚠️ Last error: {doc['ocr_error']}")
        with col_btn:
            if ocr_status != "done":
                if MISTRAL_API_KEY:
                    if st.button("▶ Run OCR", key=f"ocr_{doc['doc_id']}"):
                        s  = st.empty()
                        p  = st.progress(0)
                        ok = run_ocr_for_session_doc(doc_path, status_widget=s, progress_widget=p)
                        if ok:
                            st.rerun()
                else:
                    st.caption("❌ No Mistral key")

    # Run OCR on ALL pending docs at once
    pending_docs = [Path(d["_path"]) for d in session_docs if d.get("ocr_status") != "done"]
    if pending_docs and MISTRAL_API_KEY:
        if st.button(f"🚀 Run OCR on all {len(pending_docs)} pending document(s)", type="primary"):
            status_box = st.empty()
            prog       = st.progress(0)
            for i, doc_path in enumerate(pending_docs, 1):
                status_box.info(f"OCR {i}/{len(pending_docs)}: {doc_path.name}…")
                run_ocr_for_session_doc(doc_path, status_widget=status_box)
                prog.progress(i / len(pending_docs))
            (active_sess_dir / "processing" / "combined_ocr.txt").unlink(missing_ok=True)
            update_session_meta(active_sess_dir, {"status": "ocr_done"})
            st.success("All OCR runs complete.")
            st.rerun()
else:
    st.info("No documents uploaded yet. Use the uploader above to add files to this session.")

# ── 2c. Build / preview merged OCR text ───────────────────────────────────────
with st.spinner("Merging OCR text from session documents…"):
    final_ocr_text            = get_combined_ocr_text(active_sess_dir)
    st.session_state.ocr_text = final_ocr_text or ""

if not st.session_state.ocr_text.strip():
    st.warning(
        "⚠️ No OCR text available yet. Upload and OCR at least one document above, "
        "or verify results will be marked NOT_FOUND."
    )
    # ── Debug: show what's on disk so we can trace the path issue ──────────────
    with st.expander("🔎 Debug — OCR directory contents", expanded=True):
        for doc in list_session_documents(active_sess_dir):
            ocr_dir = Path(doc["_path"]) / "ocr"
            st.markdown(f"**{doc['doc_id']}** — OCR dir: `{ocr_dir}`  exists: `{ocr_dir.exists()}`")
            if ocr_dir.exists():
                all_files = list(ocr_dir.rglob("*"))
                if all_files:
                    for f in sorted(all_files)[:40]:
                        st.code(str(f.relative_to(ocr_dir)), language="text")
                else:
                    st.caption("(empty directory)")
else:
    st.success(
        f"✅ OCR ready — {len(st.session_state.ocr_text):,} chars from "
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

        progress    = st.progress(0, text="Starting verification…")
        status_box  = st.empty()
        t0          = time.time()
        raw_reply   = None

        try:
            # ✅ Use batch runner instead of single call
            verifications, raw_reply = run_verification_in_batches(
                answers=answers,
                ocr_text=st.session_state.ocr_text,
                model=st.session_state.model_id,
                api_key=st.session_state.api_key,
                batch_size=5,          # ✅ tune: lower = safer, higher = faster
                status_widget=status_box,
            )
            progress.progress(80, text="Computing scores…")

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

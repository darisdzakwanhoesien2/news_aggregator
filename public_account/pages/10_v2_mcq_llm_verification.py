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
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
USER_DATA_DIR = BASE_DIR / "user_data"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
# ensure data + logs exist (prevent DataDir missing NameErrors)
LOG_DIR = BASE_DIR / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(BASE_DIR / ".env")

OPENROUTER_API_URL    = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_MODELS_URL = os.getenv("OPENROUTER_MODELS_URL", "https://openrouter.ai/api/v1/models")
DEFAULT_MODEL         = "meta-llama/llama-3.1-8b-instruct:free"

# Mistral OCR config (used by the inline Bulk OCR runner)
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_BASE    = "https://api.mistral.ai/v1"
MISTRAL_HEADERS = {"Authorization": f"Bearer {MISTRAL_API_KEY}"} if MISTRAL_API_KEY else {}

CHOICE_SCORE = {"A": 3, "B": 2, "C": 1, "D": 0, "": 0}
MAX_SCORE_PER_QUESTION = 3

# ══════════════════════════════════════════════════════════════════════════════
# ESG MCQ — loaded from data/esg_mcq.json  (edit questions there, not here)
# ══════════════════════════════════════════════════════════════════════════════
ESG_MCQ_JSON = DATA_DIR / "esg_mcq.json"

def _load_esg_mcq() -> list[dict]:
    """Load questions from JSON file; return empty list if missing/broken."""
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

# Add safe_name util
def safe_name(name: str) -> str:
    """Sanitize a filename to be safe for all OS."""
    if not name:
        return "file"
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


# ── ADD THESE TWO FUNCTIONS (ported from 0_0_0_2_Bulk_OCR.py) ─────────────────

def safe_image_name(raw_id: str, fallback: str) -> str:
    """
    Sanitize an image ID from Mistral into a valid filename.
    Keeps the extension if present, strips all path components.
    """
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
    """
    Run Mistral OCR on a list of file paths.
    Mirrors the working pipeline in 0_0_0_2_Bulk_OCR.py exactly.
    Returns a list of created bundle directories (Path objects).
    """
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

    log = _load_log()
    created_bundles: list = []
    total = len(files)

    for i, file_path in enumerate(files, start=1):
        file_path = Path(file_path)
        doc_key = safe_name(file_path.name)

        if status_widget:
            status_widget.info(f"Processing {i}/{total}: {file_path.name}")

        # ── Resume-safe: skip already processed ───────────────────────────
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
            # ── 1. Upload file to Mistral ──────────────────────────────────
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

            # ── 2. Get signed URL ──────────────────────────────────────────
            r = requests.get(
                f"{MISTRAL_BASE}/files/{file_id}/url",
                headers=headers,
                timeout=60,
            )
            if r.status_code != 200:
                raise RuntimeError(f"Signed URL failed ({r.status_code}): {r.text}")
            signed_url = r.json()["url"]

            # ── 3. Run OCR ─────────────────────────────────────────────────
            payload = {
                "model": "mistral-ocr-latest",
                "document": {
                    "type": "document_url",
                    "document_url": signed_url,
                },
                "include_image_base64": True,
            }
            r = requests.post(
                f"{MISTRAL_BASE}/ocr",
                headers={**headers, "Content-Type": "application/json"},
                json=payload,
                timeout=300,
            )
            if r.status_code != 200:
                raise RuntimeError(f"OCR failed ({r.status_code}): {r.text}")

            result = r.json()

            # ── 4. Save full JSON ──────────────────────────────────────────
            json_path = out_root / "ocr_result.json"
            json_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            # ── 5. Save pages & images ─────────────────────────────────────
            pages = result.get("pages", [])
            img_counter = 0

            for p in pages:
                idx = p.get("index", 0)
                md  = p.get("markdown", "")
                cleaned = clean_markdown(md)
                (pages_dir / f"page_{idx:04d}.md").write_text(cleaned, encoding="utf-8")

                for img in p.get("images", []):
                    b64_data = img.get("image_base64")
                    if not b64_data:
                        continue
                    # Strip data URI prefix if present (e.g. "data:image/png;base64,...")
                    if "," in b64_data:
                        b64_data = b64_data.split(",", 1)[1]
                    try:
                        img_bytes = base64.b64decode(b64_data)
                    except Exception:
                        if status_widget:
                            status_widget.warning(f"⚠ Could not decode image on page {idx}, skipping.")
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

# ══════════════════════════════════════════════════════════════════════════════
# DATA DISCOVERY HELPERS
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

def ensure_companies_from_users() -> list[str]:
    """
    Create company folders under DATA_DIR for any users defined in users.json.
    Returns a list of created company folder names (empty if none created).
    This is a minimal, safe fallback to avoid NameError when no company folders exist.
    """
    created = []
    users_file = BASE_DIR / "users.json"
    if not users_file.exists():
        return created
    try:
        raw = json.loads(users_file.read_text(encoding="utf-8") or "{}")
        # Normalize to a mapping of username -> meta
        if isinstance(raw, dict):
            users_map = raw
        elif isinstance(raw, list):
            users_map = { (u.get("username") or u.get("user") or u.get("id") or str(i)): u for i, u in enumerate(raw) }
        else:
            return created
        for uname in users_map.keys():
            if not uname or not isinstance(uname, str):
                continue
            cand = DATA_DIR / uname
            if not cand.exists():
                try:
                    cand.mkdir(parents=True, exist_ok=True)
                    created.append(uname)
                except Exception:
                    # ignore creation failures
                    continue
    except Exception:
        return created
    return created


def list_answer_files(company_dir: Path) -> list[Path]:
    candidate_dir = company_dir / "mcq_answers"
    if candidate_dir.exists() and candidate_dir.is_dir():
        return sorted(candidate_dir.glob("*.json"))
    return sorted(company_dir.glob("*.json"))

# ══════════════════════════════════════════════════════════════════════════════
# CH
def chunk_text(text: str, size: int = 1200, overlap: int = 250) -> list[str]:
    """Split text into overlapping chunks (size chars, overlap chars)."""
    if not text:
        return []
    chunks: list[str] = []
    i = 0
    L = len(text)
    # Prevent infinite loop if overlap >= size
    step = max(1, size - overlap)
    while i < L:
        chunks.append(text[i: min(i + size, L)])
        i += step
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
st.header("Step 1 — Select Company & Answer Source")

companies = list_companies()
if not companies:
    created = ensure_companies_from_users()
    companies = list_companies()
    if created:
        st.info(f"Created {len(created)} company folder(s) from users (UKM).")
    else:
        st.error("No company folders found in the data directory.")
        st.stop()

col1, col2 = st.columns(2)
with col1:
    company_name = st.selectbox("Company", options=companies)

company_dir  = DATA_DIR / company_name

# Let the user pick whether to load an answer file or fill answers from ESG_MCQ
with col2:
    answer_mode = st.radio("Answer source", ["Load from file", "Use ESG question set"], index=1)

# Persist answers across reruns instead of wiping them each run
answers: list[dict] = []
selected_file = None
if "answer_data" not in st.session_state:
    st.session_state["answer_data"] = None

# restore previously collected/loaded answers
if st.session_state.get("answer_data"):
    answers = st.session_state.answer_data.get("answers", []) or []

if answer_mode == "Load from file":
    answer_files = list_answer_files(company_dir)
    if not answer_files:
        st.warning(f"No MCQ answer files found for **{company_name}**.")
    else:
        selected_file = st.selectbox(
            "MCQ Answer File", options=answer_files,
            format_func=lambda p: p.name,
        )
        if selected_file:
            answer_data = load_json(selected_file)
            if not answer_data:
                st.error(f"Could not load {selected_file.name}")
            else:
                # persist loaded answers and filename to session_state
                answer_data = answer_data if isinstance(answer_data, dict) else {"answers": []}
                answer_data["source_file"] = selected_file.name
                st.session_state.answer_data = answer_data
                answers = answer_data.get("answers", [])
                with st.expander("📄 Answer file metadata", expanded=False):
                    st.json({
                        "company":     answer_data.get("company"),
                        "timestamp":   answer_data.get("timestamp"),
                        "mode":        answer_data.get("mode"),
                        "n_answers":   len(answers),
                        "source_mode": answer_data.get("source_mode", ""),
                    })

elif answer_mode == "Use ESG question set":
    if not ESG_MCQ:
        st.error("ESG question set not found. Place a valid data/esg_mcq.json file.")
    else:
        st.markdown(f"Using ESG question set ({len(ESG_MCQ)} questions). Fill answers below.")
        # Render a form to collect selected answers for each question
        with st.form("esg_answers_form", clear_on_submit=False):
            esg_answers = []
            for q in ESG_MCQ:
                qid = str(q.get("id") or q.get("ID") or q.get("qid") or f"q_{len(esg_answers)+1}")
                pillar = q.get("pillar", q.get("Pillar", ""))
                question_text = q.get("question", q.get("text", ""))
                # determine choices
                raw_choices = q.get("choices") or q.get("options") or q.get("answers") or q.get("choices_map") or []
                opts = []
                # normalize choices into list of tuples (letter, text)
                if isinstance(raw_choices, dict):
                    for k, v in raw_choices.items():
                        opts.append((str(k).upper(), str(v)))
                elif isinstance(raw_choices, list):
                    letters = ["A", "B", "C", "D", "E"]
                    for i, item in enumerate(raw_choices):
                        letter = letters[i] if i < len(letters) else str(i+1)
                        opts.append((letter, str(item)))
                else:
                    opts = [("A", "A"), ("B", "B"), ("C", "C"), ("D", "D")]

                # build display label and widget keys
                choice_labels = [f"{ltr}: {txt}" for ltr, txt in opts]
                default_idx = 0
                sel = st.selectbox(f"{qid} — {pillar}\n{question_text}", options=choice_labels, key=f"esg_sel_{qid}")
                selected_letter = sel.split(":", 1)[0].strip()
                # allow optional selected_text override (pre-fill with option text)
                opt_map = {ltr: txt for ltr, txt in opts}
                selected_text = st.text_input(f"Selected text for {qid} (optional)", value=opt_map.get(selected_letter, ""), key=f"esg_text_{qid}")
                esg_answers.append({
                    "id": qid,
                    "pillar": pillar,
                    "question": question_text,
                    "selected": selected_letter,
                    "selected_text": selected_text,
                })
            submitted = st.form_submit_button("Use these answers")
        if submitted:
            answers = esg_answers
            st.success(f"Collected {len(answers)} answers from ESG question set.")
            st.session_state.answer_data = {
                "company": company_name,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "mode": "esg_mcq_interactive",
                "source_file": "interactive_esg",
                "answers": answers,
            }
# if we still have no answers, stop here
if not answers:
    st.stop()

# ── Step 2 ─────────────────────────────────────────────────────────────────────
st.header("Step 2 — OCR Document Text")

# Bulk OCR storage locations (shared with Bulk OCR page)
TMP_DIR = BASE_DIR / "data" / "thesis_pdf"       # temporary uploaded files
OUT_DIR = BASE_DIR / "data" / "thesis_dataset"   # OCR outputs produced by Bulk OCR
TMP_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 2 · Document source mode ───────────────────────────────────────────
st.markdown("#### 📄 Document Source")
source_mode = st.radio(
    "How will you attach supporting documents?",
    [
        "📂 Use existing company docs",
        "📎 Upload per question",
        "📤 Upload at end (general)",
    ],
    key="q_source_mode",
    horizontal=True,
)

# root where Bulk OCR writes output bundles (use OUT_DIR)
ocr_root = OUT_DIR
ocr_docs = [d.name for d in sorted(ocr_root.iterdir()) if d.is_dir()] if ocr_root.exists() else []

# restore any persisted selection/uploads
selected_ocr_bundle = None
if st.session_state.get("selected_ocr_bundle"):
    try:
        cand = Path(st.session_state.selected_ocr_bundle)
        if cand.exists():
            selected_ocr_bundle = cand
    except Exception:
        selected_ocr_bundle = None

uploaded_bundle_paths = list(st.session_state.get("uploaded_bundle_paths", []))

if source_mode == "📂 Use existing company docs":
    if not ocr_docs:
        st.info("No Bulk OCR bundles found in data/thesis_dataset. Run the Bulk OCR page to create bundles.")
    else:
        sel_name = st.selectbox("Choose an OCR bundle from Bulk OCR outputs", options=ocr_docs, index=0 if ocr_docs else 0)
        if sel_name:
            selected_ocr_bundle = ocr_root / sel_name
            st.session_state.selected_ocr_bundle = str(selected_ocr_bundle)
            st.caption(f"Selected OCR bundle: {selected_ocr_bundle.name}")

elif source_mode in ("📎 Upload per question", "📤 Upload at end (general)"):
    st.caption("Upload PDFs / images here. Files are saved to the Bulk OCR upload folder for later OCR processing.")
    uploads = st.file_uploader(
        "Attach supporting document(s)",
        type=["pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="step2_uploads",
    )
    if uploads:
        saved = []
        # Create a folder per run/company for clarity (persist folder name to session)
        run_tag = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        dest_dir = TMP_DIR / f"{company_name}_{run_tag}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        for f in uploads:
            try:
                out_path = dest_dir / safe_name(f.name)
                out_path.write_bytes(f.getbuffer())
                saved.append(out_path)
                uploaded_bundle_paths.append(str(out_path))
            except Exception as e:
                st.warning(f"Could not save {f.name}: {e}")
        # persist uploaded paths and folder so reruns keep them
        st.session_state.uploaded_bundle_dir = str(dest_dir)
        st.session_state.uploaded_bundle_paths = uploaded_bundle_paths
        st.success(f"Saved {len(saved)} file(s) to {str(dest_dir.relative_to(BASE_DIR))}")

        # Offer to run OCR now (runs the same pipeline as Bulk OCR page)
        if not MISTRAL_API_KEY:
            st.warning("MISTRAL_API_KEY not found in .env — cannot run OCR here. Open the Bulk OCR page to process these files.")
            st.markdown("Open the Bulk OCR page to process these files: [Bulk OCR](/pages/0_0_0_2_Bulk_OCR.py)")
        else:
            run_now = st.button("🚀 Run OCR now for uploaded files", key=f"run_ocr_{run_tag}")
            if run_now:
                status = st.empty()
                progress = st.progress(0)
                files_to_process = [Path(p) for p in uploaded_bundle_paths]
                created_bundles = run_mistral_ocr(files_to_process, OUT_DIR, TMP_DIR, headers=MISTRAL_HEADERS, status_widget=status, progress_widget=progress)
                if created_bundles:
                    # select first created bundle by default
                    st.session_state.selected_ocr_bundle = str(created_bundles[0])
                    st.success(f"OCR finished — created {len(created_bundles)} bundle(s). Selected `{created_bundles[0].name}` for verification.")
                else:
                    st.error("OCR run completed but no bundles were created. Check logs.")
# Now build OCR text: priority —
# 1) If user selected an OCR bundle from OUT_DIR, use it
# 2) Else use the app's auto-detect (existing behaviour)
with st.spinner("Locating / loading OCR text…"):
    final_ocr_text = ""
    ocr_source = None
    # coerce persisted selected bundle if not set above
    if not selected_ocr_bundle and isinstance(st.session_state.get("selected_ocr_bundle"), str):
        try:
            cand = Path(st.session_state.selected_ocr_bundle)
            if cand.exists():
                selected_ocr_bundle = cand
        except Exception:
            selected_ocr_bundle = None

    if selected_ocr_bundle and selected_ocr_bundle.exists():
        final_ocr_text = collect_ocr_text(selected_ocr_bundle, company_base=company_dir)
        ocr_source = selected_ocr_bundle
    else:
        # fallback to automatic discovery (keeps previous behaviour)
        auto_ocr_text, auto_detected_source = get_ocr_text(company_dir)
        final_ocr_text = auto_ocr_text or ""
        ocr_source = auto_detected_source

st.session_state.ocr_text = final_ocr_text or ""
# expose the chosen source for downstream UI
auto_source = ocr_source

# Compute safe source_file_label for downstream usage (avoids selected_file.name errors)
source_file_label = (st.session_state.get("answer_data") or {}).get("source_file") or (getattr(selected_file, "name", None) if 'selected_file' in locals() else None) or "interactive_esg"

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

            # helpful safe label for persisted source
            source_file_label = (st.session_state.get("answer_data") or {}).get("source_file") or "interactive_esg"

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
                    "source_file": source_file_label,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "model": st.session_state.model_id,
                    "status": "parse_error",
                    "error": "LLM response could not be parsed as JSON",
                    "raw_llm_reply": raw_reply,
                    "verifications": verifications,
                }
                out_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                # per-user session: save under user_data/<user>/sessions/<ts>/*
                current_user = st.session_state.get("user") or (st.experimental_get_query_params().get("user", [None])[0])
                if current_user:
                    sess_dir = USER_DATA_DIR / current_user / "sessions" / ts
                    sess_dir.mkdir(parents=True, exist_ok=True)
                    (sess_dir / "verification.json").write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    try:
                        (sess_dir / "raw_llm_reply.txt").write_text(raw_reply or "", encoding="utf-8")
                        # save score table if available
                        df_fail = compute_scores(answers, verifications)
                        (sess_dir / "scores.csv").write_text(df_fail.to_csv(index=False), encoding="utf-8")
                    except Exception:
                        pass
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
                    "company": company_name,
                    "source_file": source_file_label,
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
                # persist into user session folder if user present
                current_user = st.session_state.get("user") or (st.experimental_get_query_params().get("user", [None])[0])
                if current_user:
                    sess_dir = USER_DATA_DIR / current_user / "sessions" / ts
                    sess_dir.mkdir(parents=True, exist_ok=True)
                    (sess_dir / "verification.json").write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    try:
                        (sess_dir / "raw_llm_reply.txt").write_text(raw_reply or "", encoding="utf-8")
                        score_df.to_csv(sess_dir / "scores.csv", index=False)
                    except Exception:
                        pass
                elapsed = time.time() - t0
                progress.progress(100, text=f"Done in {elapsed:.1f}s")
                st.success(f"✅ Verification complete in {elapsed:.1f}s — saved to `{out_path.name}`")
        except Exception as e:
            # Always save an error file with as much context as possible
            err_info = {
                "company": company_name,
                # use safe source_file_label (may come from session)
                "source_file": source_file_label,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "model": st.session_state.model_id,
                "status": "error",
                "error": str(e),
                "raw_llm_reply": raw_reply,
            }
            try:
                out_path.write_text(json.dumps(err_info, ensure_ascii=False, indent=2), encoding="utf-8")
                current_user = st.session_state.get("user") or (st.experimental_get_query_params().get("user", [None])[0])
                if current_user:
                    sess_dir = USER_DATA_DIR / current_user / "sessions" / ts
                    sess_dir.mkdir(parents=True, exist_ok=True)
                    (sess_dir / "error.json").write_text(json.dumps(err_info, ensure_ascii=False, indent=2), encoding="utf-8")
                    if raw_reply:
                        (sess_dir / "raw_llm_reply.txt").write_text(raw_reply, encoding="utf-8")
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

# Prevent the concatenated "My Files" / other page code below from running
# when this file is served as the MCQ page. This avoids multiple calls to
# st.set_page_config() and other duplicate Streamlit top-level calls.
st.stop()

"""
────────────────────────────────────────────────────────────────────────────────
My Files Page
────────────────────────────────────────────────────────────────────────────────
"""

import streamlit as st
from pathlib import Path
import json
from datetime import datetime

ROOT = Path(__file__).parent.parent
USER_FILES_DIR = ROOT / "user_files"
USER_FILES_DIR.mkdir(exist_ok=True)

def _ensure_user():
    user = st.session_state.get("user")
    if not user:
        params = st.experimental_get_query_params()
        if "user" in params and params["user"]:
            st.session_state["user"] = params["user"][0]
            user = st.session_state["user"]
    return user

def load_metadata(user: str) -> list:
    mpath = USER_FILES_DIR / user / "metadata.json"
    if not mpath.exists():
        return []
    try:
        return json.loads(mpath.read_text(encoding="utf-8") or "[]")
    except Exception:
        return []

def save_metadata(user: str, meta: list):
    mpath = USER_FILES_DIR / user / "metadata.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

def save_uploaded_file(user: str, uploaded):
    user_dir = USER_FILES_DIR / user
    user_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    fname = f"{ts}_{uploaded.name}"
    out_path = user_dir / fname
    with out_path.open("wb") as f:
        f.write(uploaded.getbuffer())
    meta = load_metadata(user)
    meta.append({
        "filename": fname,
        "original_name": uploaded.name,
        "content_type": uploaded.type,
        "size": uploaded.size,
        "uploaded_at": datetime.utcnow().isoformat() + "Z",
        "title": "",
        "description": "",
    })
    save_metadata(user, meta)
    return fname

st.set_page_config(page_title="My Files", layout="centered")
st.title("📁 My Files")

user = _ensure_user()
if not user:
    st.warning("You need to be logged in to upload or view files.")
    st.markdown("- [Go to Login](/login)")
    st.stop()

st.markdown(f"**Logged in as:** `{user}`")

# Upload UI
with st.form("upload_form"):
    st.subheader("Upload files")
    title = st.text_input("Title (optional)")
    description = st.text_area("Description (optional)")
    files = st.file_uploader("Choose file(s) to upload", accept_multiple_files=True)
    submit = st.form_submit_button("Upload")
if submit and files:
    imported = 0
    meta = load_metadata(user)
    for f in files:
        saved = save_uploaded_file(user, f)
        # update the latest metadata entry with title/description
        if meta:
            meta[-1]["title"] = title
            meta[-1]["description"] = description
        imported += 1
    save_metadata(user, meta)
    st.success(f"Uploaded {imported} file(s).")

# List existing files
st.subheader("Your uploaded files")
meta = load_metadata(user)
if not meta:
    st.info("No files uploaded yet.")
else:
    for entry in reversed(meta):
        fn = entry["filename"]
        user_file = USER_FILES_DIR / user / fn
        col1, col2, col3 = st.columns([4, 1, 1])
        with col1:
            st.markdown(f"**{entry.get('title') or entry['original_name']}** — _{entry.get('description','')}_")
            st.caption(f"{entry['original_name']} · {entry['content_type']} · {entry['size']} bytes · {entry['uploaded_at']}")
        with col2:
            if user_file.exists():
                data = user_file.read_bytes()
                st.download_button("Download", data=data, file_name=entry["original_name"], key=f"dl_{fn}")
        with col3:
            if st.button("Delete", key=f"del_{fn}"):
                try:
                    user_file.unlink()
                except Exception:
                    pass
                # remove from metadata
                m2 = [m for m in meta if m["filename"] != fn]
                save_metadata(user, m2)
                st.experimental_rerun()

"""
────────────────────────────────────────────────────────────────────────────────
Admin / UKM Overview Page
────────────────────────────────────────────────────────────────────────────────
"""

import streamlit as st
from pathlib import Path
import json
from datetime import datetime

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"

# ...existing code...
DATA_FILE = Path(__file__).parent.parent / "users.json"

# add per-user file helpers
USER_FILES_DIR = Path(__file__).parent.parent / "user_files"

def load_user_files_meta(username: str) -> list:
    mpath = USER_FILES_DIR / username / "metadata.json"
    if not mpath.exists():
        return []
    try:
        return json.loads(mpath.read_text(encoding="utf-8") or "[]")
    except Exception:
        return []

# ── Admin / UKM role handling ─────────────────────────────────────────────────
# (moved up for visibility)

# ...existing code...
with st.container():
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Admin / UKM Overview")
    st.markdown("---")

    # Role-based content
    role = st.session_state.get("role")
    user_key = st.session_state.get("user")

    if role == "admin":
        st.markdown("### 🔧 Admin actions")
        # ...existing admin code...

    elif role == "UKM":
        st.markdown("### ✅ UKM actions")
        st.info("As a UKM you can fill in your profile/form and submit answers.")
        if st.button("✏️ Fill Profile / Form (placeholder)"):
            st.info("Opening the UKM form... (implement your form page and navigate here)")
        st.markdown("---")
        st.markdown("Your recent submissions / verifications will appear here (not implemented).")

        # show uploaded files and link to manage files page
        st.markdown("#### Files")
        user_files = load_user_files_meta(user_key)
        if user_files:
            for e in reversed(user_files):
                st.markdown(f"- **{e.get('title') or e['original_name']}** — {e.get('uploaded_at')}")
        else:
            st.info("No files uploaded. Manage your files on the Files page.")
        st.markdown("- [Manage my files](/ukm_files)")

    elif role in ("Supplier", "Bank"):
        # ...existing code...
        if ukm_users:
            # ...existing code...
            if sel:
                st.markdown(f"#### Details for {sel}")
                sel_user = users.get(sel, {})
                st.json({k: v for k, v in sel_user.items() if k not in ("salt","password_hash")})

                # show selected UKM files
                st.markdown("##### Uploaded files")
                sel_meta = load_user_files_meta(sel)
                if sel_meta:
                    for e in reversed(sel_meta):
                        st.markdown(f"- **{e.get('title') or e['original_name']}** — {e.get('uploaded_at')}")
                    st.markdown(f"- [Open files for {sel}](/ukm_files?user={sel})")
                else:
                    st.info("No files uploaded by this UKM.")
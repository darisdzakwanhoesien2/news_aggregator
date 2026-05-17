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
from _page_descriptions import render_page_description

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MCQ LLM Verification",
    page_icon="🔍",
    layout="wide",
)
st.title("🔍 MCQ LLM Verification & Scoring")
render_page_description(__file__)
st.caption("Verify MCQ answers against OCR-extracted company documents using an LLM.")

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
                    temperature: float = 0.2, max_tokens: int = 2000,
                    retries: int = 3) -> str:
    """
    Send a chat-style request to the OpenRouter API.
    Retries up to `retries` times on transient HTTP errors (429, 5xx).
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

    last_err = None
    for attempt in range(retries):
        try:
            r = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=180)
            if r.status_code in (429, 500, 502, 503, 504):
                wait = 2 ** attempt
                time.sleep(wait)
                last_err = f"HTTP {r.status_code}"
                continue
            r.raise_for_status()
            j = r.json()
            choices = j.get("choices", [])
            if choices and isinstance(choices, list):
                msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
                content = msg.get("content", "")
                if content:
                    return content
                if isinstance(choices[0], dict) and "text" in choices[0]:
                    return choices[0]["text"]
            return str(j)
        except requests.exceptions.Timeout:
            last_err = "Request timed out"
            time.sleep(2 ** attempt)
        except Exception as e:
            last_err = str(e)
            time.sleep(2 ** attempt)

    return f"[LLM Error after {retries} attempts: {last_err}]"

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
    """
    Build a clear, structured prompt for the LLM.
    - Retrieves relevant OCR chunks based on question content.
    - Formats each Q&A clearly with all choices listed.
    - Includes explicit output format instructions inside the prompt.
    """
    if not ocr_text:
        ocr_snippet = "[NO OCR TEXT PROVIDED — mark all as NOT_FOUND]"
    elif len(ocr_text) <= max_ocr_chars:
        ocr_snippet = ocr_text
    else:
        # build query from all questions + selected texts for retrieval
        qs = " ".join(
            a.get("question", "") + " " + a.get("selected_text", "")
            for a in answers
        )
        chunks = chunk_text(ocr_text, size=1200, overlap=250)
        top_chunks = retrieve_relevant_chunks(qs, chunks, top_k=12)
        ocr_snippet = "\n\n---\n\n".join(top_chunks)
        if len(ocr_snippet) > max_ocr_chars:
            ocr_snippet = ocr_snippet[:max_ocr_chars]
        ocr_snippet += f"\n\n[... OCR truncated — original: {len(ocr_text):,} chars ...]"

    # build each Q&A block with full choices
    qa_blocks = []
    for a in answers:
        choices = a.get("choices", {})   # e.g. {"A": "text", "B": "text", ...}
        choices_text = ""
        if isinstance(choices, dict):
            choices_text = "\n".join(
                f"  {k}: {v}" for k, v in choices.items()
            )
        elif isinstance(choices, list):
            letters = "ABCD"
            choices_text = "\n".join(
                f"  {letters[i]}: {c}" for i, c in enumerate(choices)
            )

        qa_blocks.append(
            f"---\n"
            f"ID: {a.get('id', '')}\n"
            f"Pillar: {a.get('pillar', '')}\n"
            f"Question: {a.get('question', '')}\n"
            f"{choices_text}\n"
            f"Selected Answer: {a.get('selected', '')} — {a.get('selected_text', '')}\n"
            f"User Evidence Note: {a.get('evidence', '') or 'None'}\n"
        )

    qa_section = "\n".join(qa_blocks)

    return (
        "You are verifying MCQ answers against an OCR-extracted ESG document.\n\n"
        "=== OCR DOCUMENT TEXT (retrieved snippets) ===\n"
        f"{ocr_snippet}\n\n"
        "=== MCQ ANSWERS TO VERIFY ===\n"
        f"Total questions: {len(answers)}\n\n"
        f"{qa_section}\n\n"
        "=== OUTPUT INSTRUCTIONS ===\n"
        "Return ONLY a valid JSON array — no markdown, no extra text.\n"
        "Each element must have these exact keys:\n"
        '  "id": string (the question ID)\n'
        '  "verification_status": one of ["SUPPORTED","PARTIALLY_SUPPORTED","NOT_FOUND","CONTRADICTED"]\n'
        '  "confidence": integer 0–100\n'
        '  "evidence_quote": string (<=250 chars quote from OCR, or "")\n'
        '  "evidence_page": string (page reference, or "")\n'
        '  "reasoning": string (plain-text explanation)\n'
        '  "suggested_answer": one of "A","B","C","D" or null\n\n'
        f"Return exactly {len(answers)} objects in the array, one per question ID above.\n"
        "Output only the JSON array, starting with [ and ending with ]."
    )


def parse_verification_json(raw: str) -> list[dict] | None:
    """
    Robust parser for LLM output. Tries multiple strategies in order:
    1. Direct JSON parse (whole string is valid JSON)
    2. Fenced ```json ... ``` block
    3. First [ ... ] block in the string (even if surrounded by text)
    4. Line-by-line search for a line that starts a JSON array
    Returns None only if all strategies fail.
    """
    if not raw or not raw.strip():
        return None

    cleaned = raw.strip()

    # Strategy 1: direct parse
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return _validate_ver_list(data)
        # sometimes LLM wraps array in {"verifications": [...]}
        if isinstance(data, dict):
            for key in ("verifications", "results", "answers", "data"):
                if isinstance(data.get(key), list):
                    return _validate_ver_list(data[key])
    except json.JSONDecodeError:
        pass

    # Strategy 2: fenced code block (```json ... ``` or ``` ... ```)
    fenced = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", cleaned, re.S)
    if fenced:
        try:
            data = json.loads(fenced.group(1))
            if isinstance(data, list):
                return _validate_ver_list(data)
        except json.JSONDecodeError:
            pass

    # Strategy 3: find the outermost [ ... ] in the string
    # Use a bracket counter to handle nested arrays/objects
    start = cleaned.find("[")
    if start != -1:
        depth = 0
        end = -1
        in_string = False
        escape = False
        for i, ch in enumerate(cleaned[start:], start=start):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            candidate = cleaned[start:end + 1]
            try:
                data = json.loads(candidate)
                if isinstance(data, list):
                    return _validate_ver_list(data)
            except json.JSONDecodeError:
                # try to repair: remove trailing commas before ] or }
                repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
                try:
                    data = json.loads(repaired)
                    if isinstance(data, list):
                        return _validate_ver_list(data)
                except json.JSONDecodeError:
                    pass

    # Strategy 4: line-by-line — find a line that looks like the start of a JSON array
    lines = cleaned.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") or stripped.startswith("{\"id\""):
            candidate = "\n".join(lines[i:])
            # wrap lone object in array if needed
            if stripped.startswith("{"):
                candidate = "[" + candidate
                if not candidate.rstrip().endswith("]"):
                    candidate = candidate.rstrip().rstrip(",") + "]"
            try:
                data = json.loads(candidate)
                if isinstance(data, list):
                    return _validate_ver_list(data)
            except json.JSONDecodeError:
                pass

    return None


def _validate_ver_list(data: list) -> list[dict]:
    """
    Normalise a parsed list: ensure required keys exist and status is valid.
    Fills missing/invalid fields with safe defaults so scoring never crashes.
    """
    valid_statuses = {"SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_FOUND", "CONTRADICTED"}
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        # normalise verification_status
        status = str(item.get("verification_status", "NOT_FOUND")).upper().strip()
        # allow common LLM shortcuts
        status_map = {
            "PARTIAL": "PARTIALLY_SUPPORTED",
            "PARTIAL_SUPPORT": "PARTIALLY_SUPPORTED",
            "PARTIALLY SUPPORTED": "PARTIALLY_SUPPORTED",
            "SUPPORT": "SUPPORTED",
            "CONTRADICT": "CONTRADICTED",
            "CONTRADICTS": "CONTRADICTED",
            "NOT FOUND": "NOT_FOUND",
            "NOTFOUND": "NOT_FOUND",
        }
        status = status_map.get(status, status)
        if status not in valid_statuses:
            status = "NOT_FOUND"

        # normalise confidence
        try:
            confidence = max(0, min(100, int(float(item.get("confidence", 0)))))
        except (ValueError, TypeError):
            confidence = 0

        # normalise suggested_answer
        suggested = item.get("suggested_answer")
        if suggested not in ("A", "B", "C", "D", None):
            suggested = None

        out.append({
            "id":                  str(item.get("id", "")),
            "verification_status": status,
            "confidence":          confidence,
            "evidence_quote":      str(item.get("evidence_quote", ""))[:300],
            "evidence_page":       str(item.get("evidence_page", "")),
            "reasoning":           str(item.get("reasoning", "")),
            "suggested_answer":    suggested,
        })
    return out

# ...existing code...

if run_btn:
    if not answers:
        st.error("No answers found in the selected file.")
    else:
        out_dir  = company_dir / "mcq_answers"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        out_path = out_dir / f"{ts}_verification.json"

        # ── batch answers to avoid token limits (max 15 per call) ──────────
        BATCH_SIZE = 15
        batches = [answers[i:i + BATCH_SIZE] for i in range(0, len(answers), BATCH_SIZE)]
        all_verifications: list[dict] = []
        parse_errors: list[str] = []

        progress = st.progress(0, text="Starting LLM verification…")
        t0 = time.time()

        try:
            for batch_idx, batch in enumerate(batches):
                pct = int((batch_idx / len(batches)) * 80)
                progress.progress(pct, text=f"Verifying batch {batch_idx + 1}/{len(batches)} ({len(batch)} questions)…")

                prompt_user = build_verification_prompt(
                    batch,
                    st.session_state.ocr_text,
                    max_ocr_chars=14000,
                )
                messages = [
                    {"role": "system", "content": VERIFICATION_SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt_user},
                ]

                raw_reply = call_openrouter(
                    messages=messages,
                    model=st.session_state.model_id,
                    api_key=st.session_state.api_key,
                    temperature=0.1,
                    max_tokens=4000,
                    retries=3,
                )

                # track raw replies per batch
                st.session_state.raw_llm_reply += (
                    f"\n\n=== Batch {batch_idx + 1}/{len(batches)} ===\n{raw_reply}"
                )

                verifications = parse_verification_json(raw_reply)
                if verifications is None:
                    parse_errors.append(f"Batch {batch_idx + 1}: could not parse LLM response")
                    # fallback: NOT_FOUND for each question in this batch
                    for a in batch:
                        all_verifications.append({
                            "id": a["id"],
                            "verification_status": "NOT_FOUND",
                            "confidence": 0,
                            "evidence_quote": "",
                            "evidence_page": "",
                            "reasoning": f"LLM response unparsable (batch {batch_idx + 1}).",
                            "suggested_answer": None,
                        })
                else:
                    all_verifications.extend(verifications)

            progress.progress(85, text="Filling missing answers…")

            # ensure every question has a verification entry
            ver_map = {v["id"]: v for v in all_verifications}
            for a in answers:
                if a["id"] not in ver_map:
                    all_verifications.append({
                        "id": a["id"],
                        "verification_status": "NOT_FOUND",
                        "confidence": 0,
                        "evidence_quote": "",
                        "evidence_page": "",
                        "reasoning": "Not returned by LLM.",
                        "suggested_answer": None,
                    })

            progress.progress(90, text="Computing scores…")
            score_df = compute_scores(answers, all_verifications)
            st.session_state.verification = all_verifications
            st.session_state.score_df = score_df

            result_payload = {
                "company":           company_name,
                "source_file":       selected_file.name,
                "timestamp":         datetime.utcnow().isoformat() + "Z",
                "model":             st.session_state.model_id,
                "status":            "ok" if not parse_errors else "partial_parse_error",
                "parse_errors":      parse_errors,
                "total_final_score": float(score_df["Final Score"].sum()),
                "total_max_score":   int(score_df["Max Score"].sum()),
                "total_raw_score":   int(score_df["Raw Score"].sum()),
                "pct_verified":      round(score_df["Final Score"].sum() / score_df["Max Score"].sum() * 100, 2)
                                     if score_df["Max Score"].sum() else 0,
                "verifications":     all_verifications,
                "scores":            score_df.to_dict(orient="records"),
                "raw_llm_reply":     st.session_state.raw_llm_reply,
            }
            out_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            elapsed = time.time() - t0
            progress.progress(100, text=f"Done in {elapsed:.1f}s")

            if parse_errors:
                st.warning(f"⚠️ {len(parse_errors)} batch(es) had parse errors — those questions marked NOT_FOUND:\n" + "\n".join(parse_errors))
            st.success(f"✅ Verification complete in {elapsed:.1f}s — saved to `{out_path.name}`")

        except Exception as e:
            err_info = {
                "company":       company_name,
                "source_file":   selected_file.name,
                "timestamp":     datetime.utcnow().isoformat() + "Z",
                "model":         st.session_state.model_id,
                "status":        "error",
                "error":         str(e),
                "raw_llm_reply": st.session_state.raw_llm_reply,
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

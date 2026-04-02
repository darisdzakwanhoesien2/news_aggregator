"""
────────────────────────────────────────────────────────────────────────────────
ESG-SME MCQ Verification Pipeline
────────────────────────────────────────────────────────────────────────────────
Pipeline:
  Step 1 · Interactive MCQ Questionnaire (manual answers + document attachment)
  Step 2 · Upload company PDF(s) → Mistral OCR → save to data/<company_name>/
  Step 3 · Run 1-shot LLM call → answer all ESG-SME MCQs from the OCR text
  Step 4 · View & compare results; download JSON

Storage layout:
  new_app/data/<company_name>/
      ocr/
          <doc_name>/
              pages/      *.md
              images/     *.jpg …
              ocr_result.json
      mcq_answers/
          <timestamp>_<model>.json
          <timestamp>_manual.json
"""

# ── std-lib ────────────────────────────────────────────────────────────────────
import os
import re
import json
import time
import base64
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ── third-party ────────────────────────────────────────────────────────────────
import requests
from requests.adapters import HTTPAdapter, Retry
import streamlit as st
from dotenv import load_dotenv

# ══════════════════════════════════════════════════════════════════════════════
# PATHS & ENV
# ══════════════════════════════════════════════════════════════════════════════
BASE_DIR = Path(__file__).resolve().parents[1]   # new_app/
DATA_DIR = BASE_DIR / "data"                     # new_app/data/
LOG_DIR  = BASE_DIR / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

MISTRAL_API_KEY       = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_BASE          = "https://api.mistral.ai/v1"

OPENROUTER_API_URL    = os.getenv("OPENROUTER_API_URL",    "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_MODELS_URL = os.getenv("OPENROUTER_MODELS_URL", "https://openrouter.ai/api/v1/models")
LMSTUDIO_DEFAULT_URL  = "http://localhost:1234/v1"
DEFAULT_OR_MODEL      = "meta-llama/llama-3.1-8b-instruct:free"
BACKEND_OPENROUTER    = "OpenRouter"
BACKEND_LMSTUDIO      = "LM Studio (Local)"

OCR_LOG_FILE = LOG_DIR / "mcq_ocr_log.json"

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
# HELPERS — SERIALIZATION
# ══════════════════════════════════════════════════════════════════════════════
def _serialize(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_serialize(o) for o in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def atomic_write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(_serialize(data), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS — FILENAME SANITISATION
# ══
def safe_name(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def safe_image_name(raw_id: str, fallback: str) -> str:
    base = re.split(r"[/\\]", raw_id)[-1]
    base = re.sub(r'[\\/*?:"<>|]', "_", base).strip() or fallback
    if not re.search(r"\.(jpg|jpeg|png|gif|webp|bmp)$", base, re.IGNORECASE):
        base += ".jpg"
    return base


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS — MISTRAL OCR
# ══════════════════════════════════════════════════════════════════════════════
def mistral_ocr(tmp_path: Path, out_root: Path, status_fn) -> dict:
    """Upload file → signed URL → OCR → save pages/images. Returns result dict."""
    pages_dir  = out_root / "pages"
    images_dir = out_root / "images"
    pages_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}"}

    status_fn("📤 Uploading to Mistral…")
    with open(tmp_path, "rb") as f:
        r = requests.post(
            f"{MISTRAL_BASE}/files",
            headers=headers,
            files={"file": (tmp_path.name, f)},
            data={"purpose": "ocr"},
            timeout=120,
        )
    if r.status_code != 200:
        raise RuntimeError(f"Upload failed ({r.status_code}): {r.text}")
    file_id = r.json()["id"]

    status_fn("🔗 Getting signed URL…")
    r = requests.get(f"{MISTRAL_BASE}/files/{file_id}/url", headers=headers, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Signed URL failed ({r.status_code}): {r.text}")
    signed_url = r.json()["url"]

    status_fn("🔍 Running OCR…")
    payload = {
        "model": "mistral-ocr-latest",
        "document": {"type": "document_url", "document_url": signed_url},
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

    (out_root / "ocr_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    img_counter = 0
    for p in result.get("pages", []):
        idx = p.get("index", 0)
        (pages_dir / f"page_{idx:04d}.md").write_text(p.get("markdown", ""), encoding="utf-8")
        for img in p.get("images", []):
            b64 = img.get("image_base64", "")
            if not b64:
                continue
            if "," in b64:
                b64 = b64.split(",", 1)[1]
            try:
                img_bytes = base64.b64decode(b64)
            except Exception:
                continue
            raw_id   = img.get("id", "")
            fallback = f"page{idx:04d}_img{img_counter:04d}.jpg"
            name     = safe_image_name(raw_id, fallback) if raw_id else fallback
            (images_dir / name).write_bytes(img_bytes)
            img_counter += 1

    return result


def collect_ocr_text(company_dir: Path) -> str:
    """Concatenate all page markdown files for a company into one string."""
    ocr_root = company_dir / "ocr"
    if not ocr_root.exists():
        return ""
    texts = []
    for doc_dir in sorted(ocr_root.iterdir()):
        pages_dir = doc_dir / "pages"
        if pages_dir.exists():
            for md in sorted(pages_dir.glob("*.md")):
                txt = md.read_text(encoding="utf-8").strip()
                if txt:
                    texts.append(f"[{doc_dir.name} / {md.name}]\n{txt}")
    return "\n\n---\n\n".join(texts)


# ---------------- Auto-evidence extraction from OCR ----------------
def extract_evidence_for_answers(
    ocr_text: str,
    answers: list[dict],
    id_to_q: dict | None = None,
    window_chars: int = 300,
) -> None:
    """
    Mutates `answers` in-place.
    For each answer, searches the full OCR text for passages relevant to the
    question + selected choice and fills:
        - evidence      : the best matching OCR snippet
        - evidence_doc  : which document/page the snippet came from
        - evidence_score: how many keyword tokens matched (0 = not found)
    Search strategy (in order of priority):
        1. Question keywords + selected choice text tokens
        2. Question keywords only
        3. Selected choice text tokens only
    """
    import re as _re

    def _tokenize(text: str, min_len: int = 3) -> list[str]:
        """Return lower-cased word tokens of length >= min_len."""
        return [t for t in _re.findall(r"\w+", text.lower()) if len(t) >= min_len]

    def _find_best_window(
        tokens: list[str], lower_text: str, full_text: str, window: int
    ) -> tuple[str, int, int]:
        """
        Slide over lower_text looking for the densest cluster of `tokens`.
        Returns (snippet, char_offset_of_best_centre, matched_token_count).
        """
        if not tokens:
            return ("", -1, 0)

        # Build list of (position, token) for every token hit in the text
        hits: list[tuple[int, str]] = []
        for tok in set(tokens):  # deduplicate
            start = 0
            while True:
                idx = lower_text.find(tok, start)
                if idx == -1:
                    break
                hits.append((idx, tok))
                start = idx + 1

        if not hits:
            return ("", -1, 0)

        hits.sort()

        # Slide a window of `window` chars and count distinct tokens inside
        best_score = 0
        best_centre = hits[0][0]
        for i, (pos, _) in enumerate(hits):
            win_end = pos + window
            distinct = set()
            for j in range(i, len(hits)):
                if hits[j][0] > win_end:
                    break
                distinct.add(hits[j][1])
            if len(distinct) > best_score:
                best_score = len(distinct)
                best_centre = pos

        start = max(0, best_centre - window // 2)
        end   = min(len(full_text), best_centre + window // 2)
        snippet = full_text[start:end].strip()
        return (snippet, best_centre, best_score)

    def _doc_from_offset(full_text: str, offset: int) -> str | None:
        """
        The collect_ocr_text() format embeds markers like:
            [docname / page_0000.md]
        Walk backwards from `offset` to find the nearest such marker.
        """
        pre = full_text[max(0, offset - 1000) : offset]
        m = _re.search(r"\[([^/\]]+?)\s*/\s*[^\]]+\]", pre)
        return m.group(1).strip() if m else None

    lower_text = ocr_text.lower() if ocr_text else ""

    for a in answers:
        qid = a.get("id", "")
        sel = (a.get("selected") or "").strip()

        # ── Resolve selected_text from question metadata if missing ────────
        if not a.get("selected_text") and id_to_q and qid:
            qmeta = id_to_q.get(qid, {})
            a["selected_text"] = qmeta.get("choices", {}).get(sel, "") if sel else ""

        # ── Skip if no OCR text ────────────────────────────────────────────
        if not ocr_text:
            a.setdefault("evidence",       "Not found (no OCR text available)")
            a.setdefault("evidence_doc",   None)
            a.setdefault("evidence_score", 0)
            continue

        question_text = a.get("question", "")
        if not question_text and id_to_q and qid:
            question_text = id_to_q.get(qid, {}).get("question", "")

        choice_text = a.get("selected_text", "")

        # ── Build token sets ───────────────────────────────────────────────
        # Exclude very common stop-words that would match everywhere
        _STOPWORDS = {
            "the", "and", "for", "are", "has", "have", "does", "not", "its",
            "their", "with", "this", "that", "from", "been", "your", "you",
            "our", "any", "all", "can", "will", "each", "into", "than",
            "more", "also", "such", "over", "other", "which", "when", "what",
        }

        q_tokens  = [t for t in _tokenize(question_text)  if t not in _STOPWORDS]
        ch_tokens = [t for t in _tokenize(choice_text)    if t not in _STOPWORDS]

        # Strategy 1: combined
        combined_tokens = list(dict.fromkeys(q_tokens + ch_tokens))  # ordered-unique
        snippet, offset, score = _find_best_window(
            combined_tokens, lower_text, ocr_text, window_chars
        )

        # Strategy 2: question only (if combined gave nothing)
        if score == 0 and q_tokens:
            snippet, offset, score = _find_best_window(
                q_tokens, lower_text, ocr_text, window_chars
            )

        # Strategy 3: choice text only (last resort)
        if score == 0 and ch_tokens:
            snippet, offset, score = _find_best_window(
                ch_tokens, lower_text, ocr_text, window_chars
            )

        if score > 0 and snippet:
            a["evidence"]       = snippet
            a["evidence_doc"]   = _doc_from_offset(ocr_text, offset)
            a["evidence_score"] = score
        else:
            a["evidence"]       = "Not found in OCR text"
            a["evidence_doc"]   = None
            a["evidence_score"] = 0

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS — LLM BACKENDS
# ══════════════════════════════════════════════════════════════════════════════
def _requests_session(retries: int = 3, backoff: float = 0.6) -> requests.Session:
    s = requests.Session()
    r = Retry(
        total=retries, backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=["POST", "GET"],
    )
    s.mount("https://", HTTPAdapter(max_retries=r))
    s.mount("http://",  HTTPAdapter(max_retries=r))
    return s


def _call_openrouter(prompt: str, model: str, api_key: str,
                     temperature: float = 0.0, max_tokens: int = 8000, retries: int = 3) -> str:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an ESG analyst. "
                    "Return ONLY a valid JSON object — no markdown, no explanation. "
                    "If information is not found, choose the most conservative option (usually D)."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens":  max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://esg-project.app",
        "X-Title":       "ESG MCQ Verifier",
    }
    s = _requests_session(retries=retries)
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = s.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=120)
            if 400 <= resp.status_code < 500:
                raise RuntimeError(f"OpenRouter {resp.status_code}: {resp.text}")
            resp.raise_for_status()
            choices = resp.json().get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return resp.text
        except RuntimeError:
            raise
        except Exception as e:
            last_exc = e
            time.sleep(min(10, 2 ** attempt))
    raise RuntimeError(f"OpenRouter failed after {retries} attempts: {last_exc}")


def _call_lmstudio(prompt: str, model: str, base_url: str,
                   temperature: float = 0.0, max_tokens: int = 8000) -> str:
    payload = {
        "messages": [
            {"role": "system", "content": "You are an ESG analyst. Output strict JSON only."},
            {"role": "user",   "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens":  max_tokens,
        "stream":      False,
    }
    if model:
        payload["model"] = model
    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions", json=payload, timeout=180
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def call_llm(prompt: str, model: str, backend: str, api_key: str = "",
             lmstudio_url: str = LMSTUDIO_DEFAULT_URL,
             temperature: float = 0.0, max_tokens: int = 8000, retries: int = 3) -> str:
    if backend == BACKEND_LMSTUDIO:
        return _call_lmstudio(prompt, model, lmstudio_url, temperature, max_tokens)
    return _call_openrouter(prompt, model, api_key, temperature, max_tokens, retries)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS — MODEL LIST
# ══════════════════════════════════════════════════════════════════════════════
def _fallback_models() -> list[dict]:
    return [
        {"id": "meta-llama/llama-3.1-8b-instruct:free",  "label": "Llama 3.1 8B (free)",  "free": True},
        {"id": "meta-llama/llama-3.3-70b-instruct:free",  "label": "Llama 3.3 70B (free)",  "free": True},
        {"id": "mistralai/mistral-7b-instruct:free",       "label": "Mistral 7B (free)",      "free": True},
        {"id": "google/gemma-3-27b-it:free",               "label": "Gemma 3 27B (free)",     "free": True},
        {"id": "deepseek/deepseek-r1:free",                "label": "DeepSeek R1 (free)",     "free": True},
        {"id": "openai/gpt-4o-mini",                       "label": "GPT-4o Mini",            "free": False},
        {"id": "openai/gpt-4o",                            "label": "GPT-4o",                 "free": False},
        {"id": "anthropic/claude-3.5-sonnet",              "label": "Claude 3.5 Sonnet",      "free": False},
        {"id": "anthropic/claude-3.5-haiku",               "label": "Claude 3.5 Haiku",       "free": False},
        {"id": "google/gemini-flash-1.5",                  "label": "Gemini 1.5 Flash",       "free": False},
    ]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_openrouter_models(api_key: Optional[str] = None) -> list[dict]:
    if not api_key:
        return _fallback_models()
    try:
        resp = requests.get(
            OPENROUTER_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}", "HTTP-Referer": "https://esg-project.app"},
            timeout=10,
        )
        resp.raise_for_status()
        raw, models = resp.json().get("data", []), []
        for m in raw:
            mid     = m.get("id", "")
            name    = m.get("name", mid)
            pricing = m.get("pricing", {})
            try:
                is_free = (
                    float(pricing.get("prompt", 1)) == 0.0
                    and float(pricing.get("completion", 1)) == 0.0
                )
            except Exception:
                is_free = str(pricing.get("prompt", "1")) == "0"
            models.append({"id": mid, "label": name, "free": is_free})
        models.sort(key=lambda x: (not x["free"], x["label"].lower()))
        return models or _fallback_models()
    except Exception:
        return _fallback_models()


def fetch_lmstudio_models(base_url: str) -> list[dict]:
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/models", timeout=5)
        resp.raise_for_status()
        return [
            {"id": m.get("id", ""), "label": m.get("id", ""), "free": True}
            for m in resp.json().get("data", []) if m.get("id")
        ]
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS — JSON PARSING
# ══════════════════════════════════════════════════════════════════════════════
def parse_json_response(text: str) -> Any:
    import ast
    if not text or not text.strip():
        raise ValueError("Empty response from model.")
    text = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).strip("` \n")
    try:
        return json.loads(text)
    except Exception:
        pass
    for match in sorted(re.findall(r'(\{[\s\S]*\}|\[[\s\S]*\])', text), key=len, reverse=True):
        try:
            return json.loads(match)
        except Exception:
            try:
                return ast.literal_eval(match)
            except Exception:
                continue
    raise ValueError(f"Could not parse JSON from:\n{text[:500]}")


# ══════════════════════════════════════════════════════════════════════════════
# MCQ PROMPT BUILDER  (1-shot)
# ══════════════════════════════════════════════════════════════════════════════
def build_mcq_prompt(company_name: str, ocr_text: str, context_chars: int = 15_000) -> str:
    trimmed = ocr_text[:context_chars]
    if len(ocr_text) > context_chars:
        trimmed += f"\n\n[NOTE: text truncated to {context_chars:,} of {len(ocr_text):,} chars]"

    q_block = "\n\n".join(
        f"Q{q['id']} [{q['pillar']}]: {q['question']}\n"
        + "\n".join(f"  {k}. {v}" for k, v in q["choices"].items())
        for q in ESG_MCQ
    )

    return f"""You are an ESG analyst evaluating the sustainability disclosures of a Small and Medium Enterprise (SME).

COMPANY: {company_name}

DOCUMENT TEXT (OCR output):
{trimmed}

────────────────────────────────────────────────────────────────────────────────
TASK: Answer ALL {len(ESG_MCQ)} multiple-choice questions below based STRICTLY on the document text.
- If the document provides clear evidence, choose the best-matching option.
- If information is absent or unclear, choose the most conservative option (usually C or D).
- Do NOT guess beyond what the text says.

Return a single JSON object with this exact schema:
{{
  "company": "<company name>",
  "timestamp": "<ISO 8601>",
  "answers": [
    {{
      "id": "E01",
      "pillar": "Environmental",
      "question": "<question text>",
      "selected": "A",
      "selected_text": "...",
      "evidence": "...",
      "confidence": "High|Medium|Low"
    }},
    ...
  ]
}}

QUESTIONS:
{q_block}
"""


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE DEFAULTS
# ══════════════════════════════════════════════════════════════════════════════
_DEFAULTS: dict = {
    "openrouter_key":    os.getenv("OPENROUTER_API_KEY", ""),
    "backend":           BACKEND_OPENROUTER,
    "lmstudio_url":      LMSTUDIO_DEFAULT_URL,
    "active_model_id":   DEFAULT_OR_MODEL,
    "lmstudio_model_id": "",
    "ocr_done":          False,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="ESG-SME MCQ Verifier", page_icon="📋", layout="wide")
st.title("📋 ESG-SME MCQ Verification Pipeline")
st.caption(
    "Answer the questionnaire → Upload docs for OCR → Run LLM → View results"
)

if not ESG_MCQ:
    st.error(
        f"❌ No questions loaded. Make sure `{ESG_MCQ_JSON}` exists and is valid JSON."
    )
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — LLM SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ LLM Settings")

    backend = st.radio(
        "Backend", [BACKEND_OPENROUTER, BACKEND_LMSTUDIO],
        index=0 if st.session_state.backend == BACKEND_OPENROUTER else 1,
        horizontal=True, key="backend_radio",
    )
    st.session_state.backend = backend

    if backend == BACKEND_OPENROUTER:
        api_key_input = st.text_input(
            "OpenRouter API Key", type="password",
            value=st.session_state.openrouter_key,
            help="https://openrouter.ai/keys",
        )
        if api_key_input.strip():
            st.session_state.openrouter_key = api_key_input.strip()
        if st.session_state.openrouter_key:
            st.success("✅ API key set")
        else:
            st.warning("⚠️ No key — only free models available")

        if st.button("🔄 Refresh model list", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        with st.spinner("Fetching models…"):
            all_or_models = fetch_openrouter_models(st.session_state.openrouter_key or None)

        tier   = st.radio("Filter", ["🆓 Free Only", "💳 Paid Only", "🔀 All"], horizontal=True)
        free_m = [m for m in all_or_models if m["free"]]
        paid_m = [m for m in all_or_models if not m["free"]]
        visible = free_m if "Free" in tier else paid_m if "Paid" in tier else all_or_models

        search = st.text_input("🔍 Search", placeholder="llama, claude…")
        if search.strip():
            visible = [m for m in visible if search.lower() in m["label"].lower()]

        v_labels   = [m["label"] for m in visible]
        id_to_m    = {m["id"]: m for m in all_or_models}
        curr_label = id_to_m.get(st.session_state.active_model_id, {}).get("label", "")
        def_idx    = v_labels.index(curr_label) if curr_label in v_labels else 0

        sel_label = st.selectbox(
            f"Model ({len(visible)} shown)", v_labels,
            index=def_idx if v_labels else 0,
        )
        sel_model = next((m["id"] for m in visible if m["label"] == sel_label), DEFAULT_OR_MODEL)
        st.session_state.active_model_id = sel_model
        active_model = sel_model

    else:
        lms_url_input = st.text_input(
            "LM Studio URL", value=st.session_state.lmstudio_url,
            help="Default: http://localhost:1234/v1",
        )
        st.session_state.lmstudio_url = lms_url_input
        lms_models = fetch_lmstudio_models(lms_url_input)

        if lms_models:
            st.success(f"✅ {len(lms_models)} model(s) loaded")
            lms_labels  = [m["label"] for m in lms_models]
            curr_lms    = st.session_state.lmstudio_model_id
            def_lms     = lms_labels.index(curr_lms) if curr_lms in lms_labels else 0
            sel_lms_lbl = st.selectbox("Local model", lms_labels, index=def_lms)
            sel_lms     = next((m for m in lms_models if m["label"] == sel_lms_lbl), None)
            if sel_lms:
                st.session_state.lmstudio_model_id = sel_lms["id"]
            active_model = st.session_state.lmstudio_model_id
        else:
            st.error("❌ Cannot reach LM Studio")
            active_model = ""

    st.divider()
    st.subheader("⚙️ Generation")
    temperature   = st.slider("Temperature", 0.0, 1.0, 0.0, 0.01)
    max_tokens    = st.number_input("Max tokens", value=8000, min_value=256, step=256)
    retries       = st.number_input("Retries", value=3, min_value=0, step=1)
    context_chars = st.number_input(
        "OCR context chars sent to LLM", value=15_000, min_value=1000, step=1000,
        help="Truncate OCR text to this many characters before sending to the LLM.",
    )

    st.divider()
    if not MISTRAL_API_KEY:
        st.error("❌ MISTRAL_API_KEY not set in .env")
    else:
        st.success("✅ Mistral API key loaded")

# ══════════════════════════════════════════════════════════════════════════════
# TABS — Interactive Questionnaire is first (Step 1)
# ══════════════════════════════════════════════════════════════════════════════
tab_questions, tab_ocr, tab_mcq, tab_results = st.tabs([
    "📝 Step 1 · MCQ Questionnaire",
    "📤 Step 2 · OCR Upload",
    "🤖 Step 3 · Run LLM MCQ",
    "📊 Step 4 · Results",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 · INTERACTIVE MCQ QUESTIONNAIRE  (the initial stage)
# ══════════════════════════════════════════════════════════════════════════════
with tab_questions:
    st.subheader("📝 ESG-SME Interactive Questionnaire")
    st.markdown(
        "Select or create a company, choose how to attach documents, "
        "answer all questions, and save."
    )

    # ── 1 · Company ────────────────────────────────────────────────────────
    st.markdown("#### 🏢 Company")
    companies_q = sorted(
        [d.name for d in DATA_DIR.iterdir() if d.is_dir() and d.name != "_tmp"]
    ) if DATA_DIR.exists() else []

    col_sel, col_new = st.columns([2, 3])
    with col_sel:
        existing = st.selectbox(
            "Select existing company", ["(create new)"] + companies_q,
            key="q_select_company",
        )
    with col_new:
        if existing == "(create new)":
            new_name = st.text_input(
                "New company name (used as folder)",
                placeholder="e.g. GreenTech_Sdn_Bhd",
                key="q_new_company",
            )
            company_chosen = new_name.strip() or None
        else:
            company_chosen = existing

    if not company_chosen:
        st.info("ℹ️ Enter or select a company name above to begin.")
        st.stop()

    company_slug = safe_name(company_chosen)
    company_dir  = DATA_DIR / company_slug
    ocr_root     = company_dir / "ocr"
    ocr_root.mkdir(parents=True, exist_ok=True)
    st.caption(f"📁 Saving to `data/{company_slug}/`")

    st.divider()

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

    ocr_docs = [d.name for d in sorted(ocr_root.iterdir()) if d.is_dir()]

    if source_mode == "📤 Upload at end (general)":
        with st.expander("📤 Upload general documents for this company", expanded=True):
            general_uploads = st.file_uploader(
                "Upload files (PDF, TXT, MD, images)",
                type=["pdf", "txt", "md", "png", "jpg", "jpeg"],
                accept_multiple_files=True,
                key="q_general_uploads",
            )
            if general_uploads:
                gen_ts  = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
                gen_dir = ocr_root / f"general_{gen_ts}"
                gen_dir.mkdir(parents=True, exist_ok=True)
                saved = []
                for f in general_uploads:
                    dest = gen_dir / f.name
                    dest.write_bytes(f.getbuffer())
                    saved.append(f.name)
                    if (f.type and f.type.startswith("text")) or f.name.lower().endswith((".txt", ".md")):
                        (gen_dir / "pages").mkdir(parents=True, exist_ok=True)
                        try:
                            (gen_dir / "pages" / "page_001.md").write_text(
                                f.getvalue().decode("utf-8"), encoding="utf-8"
                            )
                        except Exception:
                            pass
                st.success(f"✅ Saved {len(saved)} file(s) to `data/{company_slug}/ocr/{gen_dir.name}/`")
                ocr_docs = [d.name for d in sorted(ocr_root.iterdir()) if d.is_dir()]

    st.divider()

    # ── 3 · Question subset ────────────────────────────────────────────────
    st.markdown("#### 🗂️ Questions to Answer")
    all_ids = [q["id"] for q in ESG_MCQ]
    pillar_preset = st.radio(
        "Quick filter", ["All", "E – Environmental", "S – Social", "G – Governance"],
        horizontal=True, key="q_preset_pillar",
    )
    if pillar_preset == "All":
        preset_ids = all_ids
    else:
        pillar_key = pillar_preset[0]
        preset_ids = [q["id"] for q in ESG_MCQ if q["id"].startswith(pillar_key)]

    chosen_qids = st.multiselect(
        "Select individual questions (default = all in filter above)",
        options=all_ids,
        default=preset_ids,
        key="q_choose_ids",
    )

    if not chosen_qids:
        st.warning("⚠️ Select at least one question to continue.")
        st.stop()

    st.divider()

    # ── 4 · Questionnaire form ─────────────────────────────────────────────
    st.markdown(f"#### ✏️ Answers — **{company_chosen}** ({len(chosen_qids)} question(s))")

    with st.form(key="mcq_interactive_form_v2", clear_on_submit=False):
        answers_ui: list[dict] = []

        for q in [qq for qq in ESG_MCQ if qq["id"] in chosen_qids]:
            qid = q["id"]
            # with st.expander(f"**{q['id']}** [{q['pillar']}]  {q['question']}", expanded=False):
            #     selected = st.radio("Select answer", options=["", *list(q['choices'].keys())], format_func=lambda x: ("— Select —" if x == "" else x), key=f"q_choice_{qid}", horizontal=True)
            #     evidence = st.text_area("Evidence / quote (short)", key=f"q_evidence_{qid}", height=60)
            #     confidence = st.selectbox("Confidence", ["High", "Medium", "Low"], index=1, key=f"q_conf_{qid}")
            #
            #     attached = []
            #     if source_mode == "Use existing docs":
            #         attached = st.multiselect("Attach document(s)", options=ocr_docs, default=[], key=f"q_attach_{qid}")
            #     elif source_mode == "Upload per-question":
            #         upload = st.file_uploader("Upload file for this question (saved to company OCR)", type=["pdf", "txt", "md", "png", "jpg", "jpeg"], key=f"q_up_{qid}")
            #         if upload:
            #             doc_slug = safe_name(upload.name.replace('.', '_'))
            #             out_dir = ocr_root / doc_slug
            #             out_dir.mkdir(parents=True, exist_ok=True)
            #             (out_dir / upload.name).write_bytes(upload.getbuffer())
            #             if (upload.type and upload.type.startswith('text')) or upload.name.lower().endswith(('.txt', '.md')):
            #                 (out_dir / 'pages').mkdir(parents=True, exist_ok=True)
            #                 try:
            #                     (out_dir / 'pages' / 'page_001.md').write_text(upload.getvalue().decode('utf-8'), encoding='utf-8')
            #                 except Exception:
            #                     pass
            #             attached = [out_dir.name]
            #             # refresh ocr_docs
            #             ocr_docs = [d.name for d in sorted(ocr_root.iterdir()) if d.is_dir()]
            #
            #     answers_ui.append({
            #         'id': qid,
            #         'selected': selected,
            #         'selected_text': q['choices'].get(selected, '') if selected else '',
            #         'evidence': evidence,
            #         'confidence': confidence,
            #         'attached_docs': attached,
            #     })

            # Avoid nested expanders (Streamlit forbids expanders inside other expanders).
            # Use a heading + container with columns instead.
            st.markdown(f"**{qid} — {q['question']}**  \n*Pillar:* {q['pillar']}")
            col_left, col_right = st.columns([3, 1])
            with col_left:
                selected = st.radio(
                    "Select answer",
                    options=["", *list(q['choices'].keys())],
                    format_func=lambda x: ("— Select —" if x == "" else x),
                    key=f"q_choice_{qid}",
                    horizontal=True,
                )
                evidence = st.text_area("Evidence / quote (short)", key=f"q_evidence_{qid}", height=60)
            with col_right:
                confidence = st.selectbox("Confidence", ["High", "Medium", "Low"], index=1, key=f"q_conf_{qid}")

                attached = []
                if source_mode == "Use existing docs":
                    attached = st.multiselect("Attach document(s)", options=ocr_docs, default=[], key=f"q_attach_{qid}")
                elif source_mode == "Upload per-question":
                    upload = st.file_uploader(
                        "Upload file for this question (saved to company OCR)",
                        type=["pdf", "txt", "md", "png", "jpg", "jpeg"],
                        key=f"q_up_{qid}"
                    )
                    if upload:
                        doc_slug = safe_name(upload.name.replace('.', '_'))
                        out_dir = ocr_root / doc_slug
                        out_dir.mkdir(parents=True, exist_ok=True)
                        (out_dir / upload.name).write_bytes(upload.getbuffer())
                        if (upload.type and upload.type.startswith('text')) or upload.name.lower().endswith(('.txt', '.md')):
                            (out_dir / 'pages').mkdir(parents=True, exist_ok=True)
                            try:
                                (out_dir / 'pages' / 'page_001.md').write_text(upload.getvalue().decode('utf-8'), encoding='utf-8')
                            except Exception:
                                pass
                        attached = [out_dir.name]
                        # refresh ocr_docs
                        ocr_docs = [d.name for d in sorted(ocr_root.iterdir()) if d.is_dir()]

            answers_ui.append({
                'id': qid,
                'pillar': q.get('pillar', ''),
                'question': q.get('question', ''),
                'selected': selected,
                'selected_text': q['choices'].get(selected, '') if selected else '',
                'evidence': evidence,
                'confidence': confidence,
                'attached_docs': attached,
            })

        st.divider()
        submitted = st.form_submit_button(
            "💾 Save Answers", type="primary", use_container_width=True
        )

    if submitted:
        ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        ans_dir  = company_dir / "mcq_answers"
        ans_dir.mkdir(parents=True, exist_ok=True)
        out_file = ans_dir / f"{ts}_manual.json"
        record = {
            "company":      company_chosen,
            "company_slug": company_slug,
            "timestamp":    datetime.utcnow().isoformat() + "Z",
            "mode":         "manual",
            "source_mode":  source_mode,
            "answers":      answers_ui,
        }

        # --- Auto-extract evidence from OCR for manual answers
        ocr_text_here = collect_ocr_text(company_dir)
        id_to_q_map = {q["id"]: q for q in ESG_MCQ}
        extract_evidence_for_answers(ocr_text_here, record["answers"], id_to_q=id_to_q_map)

        atomic_write_json(out_file, record)
        st.success(f"✅ Saved → `data/{company_slug}/mcq_answers/{out_file.name}`")

        import pandas as pd
        df_manual = pd.DataFrame([
            {
                "ID":          a["id"],
                "Pillar":      a["pillar"],
                "Q":           a["question"][:70] + "…",
                "Answer":      a["selected"] or "—",
                "Answer Text": (a["selected_text"] or "—")[:60],
                "Confidence":  a["confidence"],
                "Docs":        ", ".join(a["attached_docs"]) or "—",
            }
            for a in answers_ui
        ])
        st.dataframe(df_manual, use_container_width=True, height=500)
        st.download_button(
            "⬇️ Download answers (JSON)",
            data=json.dumps(record, ensure_ascii=False, indent=2),
            file_name=out_file.name,
            mime="application/json",
            key="dl_manual_answers",
        )

    # ── Reference: collapsible question list ──────────────────────────────
    st.divider()
    with st.expander("📖 View all questions (reference)", expanded=False):
        ref_pillar = st.radio(
            "Filter by pillar",
            ["All", "Environmental", "Social", "Governance"],
            horizontal=True, key="q_ref_pillar",
        )
        ref_qs = ESG_MCQ if ref_pillar == "All" else [q for q in ESG_MCQ if q["pillar"] == ref_pillar]
        # View-only display (questions list)
        st.divider()
        pillar_filter_q = st.radio("Filter by pillar", ["All", "Environmental", "Social", "Governance"], horizontal=True, key="q_pillar_filter2")
        questions_shown = ESG_MCQ if pillar_filter_q == "All" else [q for q in ESG_MCQ if q['pillar'] == pillar_filter_q]

        # Avoid nested expanders: render each question as a simple heading + list
        for q in questions_shown:
            st.markdown(f"**{q['id']}** [{q['pillar']}] — {q['question']}")
            # render choices in a compact two-column layout to keep the UI tidy
            left_col, right_col = st.columns([3, 1])
            with left_col:
                for letter, text in q['choices'].items():
                    st.markdown(f"- **{letter}.** {text}")
            # small spacer column on the right (could be used for actions later)
            with right_col:
                # keep the block non-empty to avoid an IndentationError
                st.write("")

        st.caption(
            f"Total: {len(ESG_MCQ)} questions · "
            f"E: {sum(1 for q in ESG_MCQ if q['pillar']=='Environmental')} · "
            f"S: {sum(1 for q in ESG_MCQ if q['pillar']=='Social')} · "
            f"G: {sum(1 for q in ESG_MCQ if q['pillar']=='Governance')}"
        )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 · OCR UPLOAD
# ══════════════════════════════════════════════════════════════════════════════
with tab_ocr:
    st.subheader("📤 Upload Company Documents for OCR")
    st.markdown(
        "Upload PDFs or images to extract text via Mistral OCR. "
        "Extracted text is used by the LLM MCQ step."
    )

    company_name_input = st.text_input(
        "Company name (used as folder name)",
        placeholder="e.g. GreenTech_Sdn_Bhd",
        help="Folder created at data/<company_name>/",
    )
    uploaded_files = st.file_uploader(
        "Upload PDF(s) or image(s)",
        type=["pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )

    if uploaded_files and company_name_input.strip():
        company_slug_ocr = safe_name(company_name_input.strip())
        company_dir_ocr  = DATA_DIR / company_slug_ocr
        ocr_root_ocr     = company_dir_ocr / "ocr"

        st.info(
            f"📁 Will save to: `data/{company_slug_ocr}/ocr/`  \n"
            f"Files: {', '.join(f.name for f in uploaded_files)}"
        )

        if not MISTRAL_API_KEY:
            st.error("❌ Cannot run OCR — MISTRAL_API_KEY is not set in `.env`.")
        elif st.button("🚀 Run Bulk OCR", type="primary", use_container_width=True):
            ocr_log  = load_json(OCR_LOG_FILE, {})
            progress = st.progress(0)
            total    = len(uploaded_files)

            for i, uploaded in enumerate(uploaded_files, start=1):
                doc_key = f"{company_slug_ocr}/{safe_name(uploaded.name)}"
                status  = st.empty()

                if ocr_log.get(doc_key, {}).get("status") == "done":
                    status.warning(f"⏭️ Already processed — skipping: `{uploaded.name}`")
                    progress.progress(i / total)
                    continue

                tmp_path = DATA_DIR / "_tmp" / uploaded.name
                tmp_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path.write_bytes(uploaded.getbuffer())

                doc_slug = safe_name(uploaded.name.replace(".", "_"))
                out_dir  = ocr_root_ocr / doc_slug

                try:
                    mistral_ocr(
                        tmp_path, out_dir,
                        lambda msg, _n=uploaded.name: status.info(f"`{_n}` · {msg}"),
                    )
                    ocr_log[doc_key] = {
                        "status":    "done",
                        "company":   company_slug_ocr,
                        "doc":       doc_slug,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                    atomic_write_json(OCR_LOG_FILE, ocr_log)
                    status.success(f"✅ OCR complete: `{uploaded.name}`")
                except Exception as e:
                    ocr_log[doc_key] = {"status": "failed", "error": str(e)}
                    atomic_write_json(OCR_LOG_FILE, ocr_log)
                    status.error(f"❌ OCR failed for `{uploaded.name}`: {e}")

                try:
                    tmp_path.unlink()
                except Exception:
                    pass

                progress.progress(i / total)

            st.session_state.ocr_done = True
            st.success("🎉 Bulk OCR pipeline finished!")

            zip_path = DATA_DIR / f"{company_slug_ocr}_ocr.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in ocr_root_ocr.rglob("*"):
                    if p.is_file():
                        zf.write(p, arcname=p.relative_to(company_dir_ocr))
            with open(zip_path, "rb") as zf:
                st.download_button(
                    f"⬇️ Download OCR results ZIP ({company_slug_ocr})",
                    data=zf.read(),
                    file_name=f"{company_slug_ocr}_ocr.zip",
                    mime="application/zip",
                )

    elif uploaded_files and not company_name_input.strip():
        st.warning("⚠️ Please enter a company name before uploading.")

    st.divider()
    st.subheader("📁 Existing Company Folders")
    all_companies = (
        sorted([d for d in DATA_DIR.iterdir() if d.is_dir() and d.name != "_tmp"])
        if DATA_DIR.exists() else []
    )
    if all_companies:
        for c in all_companies:
            docs    = list((c / "ocr").iterdir()) if (c / "ocr").exists() else []
            answers = list((c / "mcq_answers").glob("*.json")) if (c / "mcq_answers").exists() else []
            with st.expander(f"🏢 `{c.name}` — {len(docs)} doc(s) · {len(answers)} MCQ run(s)"):
                for d in docs:
                    pages = list((d / "pages").glob("*.md"))
                    st.markdown(f"  - 📄 `{d.name}` — {len(pages)} page(s)")
    else:
        st.info("No company data yet. Upload documents above.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 · RUN LLM MCQ
# ══════════════════════════════════════════════════════════════════════════════
with tab_mcq:
    st.subheader("🤖 Run ESG-SME MCQs via LLM (1-shot)")

    llm_companies = (
        sorted([d for d in DATA_DIR.iterdir() if d.is_dir() and d.name != "_tmp"])
        if DATA_DIR.exists() else []
    )

    if not llm_companies:
        st.warning("⚠️ No company folders found. Complete Step 2 (OCR Upload) first.")
    else:
        llm_company_names     = [c.name for c in llm_companies]
        selected_company_name = st.selectbox("Select company", llm_company_names, key="mcq_company_select")
        selected_company_dir  = DATA_DIR / selected_company_name

        ocr_text = collect_ocr_text(selected_company_dir)

        if not ocr_text.strip():
            st.warning("⚠️ No OCR text found for this company. Run OCR first (Step 2).")
        else:
            st.info(
                f"📄 OCR text loaded: ~{len(ocr_text):,} chars · "
                f"Sending first {int(context_chars):,} chars to the LLM."
            )
            with st.expander("👁️ Preview OCR text (first 2 000 chars)", expanded=False):
                st.text(ocr_text[:2000])
            with st.expander("📋 Preview prompt (first 3 000 chars)", expanded=False):
                st.text(build_mcq_prompt(selected_company_name, ocr_text, int(context_chars))[:3000])

            st.markdown(f"**Model:** `{active_model}` · **Backend:** {backend}")

            if backend == BACKEND_OPENROUTER and not st.session_state.openrouter_key:
                st.error("❌ OpenRouter API key not set.")
            elif not active_model:
                st.error("❌ No LLM model selected.")
            elif st.button("🚀 Run MCQ Verification (1-shot)", type="primary", use_container_width=True):
                prompt = build_mcq_prompt(selected_company_name, ocr_text, int(context_chars))
                with st.spinner(f"Calling {active_model}…"):
                    try:
                        raw    = call_llm(
                            prompt=prompt,
                            model=active_model,
                            backend=backend,
                            api_key=st.session_state.openrouter_key,
                            lmstudio_url=st.session_state.lmstudio_url,
                            temperature=float(temperature),
                            max_tokens=int(max_tokens),
                            retries=int(retries),
                        )
                        parsed = parse_json_response(raw)
                        ok, err = True, None
                    except Exception as e:
                        raw, parsed, ok, err = "", {}, False, str(e)

                if ok:
                    st.success("✅ MCQ answers received!")
                    id_to_q = {q["id"]: q for q in ESG_MCQ}
                    for ans in parsed.get("answers", []):
                        q_meta = id_to_q.get(ans.get("id"), {})
                        ans.setdefault("question", q_meta.get("question", ""))
                        ans.setdefault("pillar",   q_meta.get("pillar", ""))
                        if not ans.get("selected_text"):
                            ans["selected_text"] = q_meta.get("choices", {}).get(ans.get("selected", ""), "")

                    # --- Auto-extract evidence from OCR for LLM answers
                    extract_evidence_for_answers(ocr_text, parsed.get("answers", []), id_to_q=id_to_q)

                    answers_dir = selected_company_dir / "mcq_answers"
                    answers_dir.mkdir(parents=True, exist_ok=True)
                    ts         = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
                    model_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", active_model)[:40]
                    out_file   = answers_dir / f"{ts}_{model_slug}.json"

                    record = {
                        "company":    selected_company_name,
                        "model":      active_model,
                        "backend":    backend,
                        "timestamp":  datetime.utcnow().isoformat() + "Z",
                        "ok":         ok,
                        "answers":    parsed.get("answers", []),
                        "raw_output": raw[:5000],
                    }
                    atomic_write_json(out_file, record)
                    st.info(f"💾 Saved to `data/{selected_company_name}/mcq_answers/{out_file.name}`")

                    import pandas as pd
                    st.subheader("📊 Answer Summary")
                    answers_llm = parsed.get("answers", [])
                    if answers_llm:
                        df_llm = pd.DataFrame([
                            {
                                "ID":          a.get("id"),
                                "Pillar":      a.get("pillar"),
                                "Question":    a.get("question", "")[:80] + "…",
                                "Answer":      a.get("selected"),
                                "Answer Text": a.get("selected_text", "")[:60],
                                "Confidence":  a.get("confidence", ""),
                                "Evidence":    a.get("evidence", "")[:80],
                            }
                            for a in answers_llm
                        ])
                        st.dataframe(df_llm, use_container_width=True, height=600)

                    st.download_button(
                        "⬇️ Download MCQ answers (JSON)",
                        data=json.dumps(record, ensure_ascii=False, indent=2),
                        file_name=f"{selected_company_name}_mcq_{ts}.json",
                        mime="application/json",
                    )
                else:
                    st.error(f"❌ LLM call failed: {err}")
                    with st.expander("🧪 Raw output"):
                        st.code(raw)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 · RESULTS VIEWER
# ══════════════════════════════════════════════════════════════════════════════
with tab_results:
    st.subheader("📊 MCQ Results Viewer")

    res_companies = (
        sorted([d for d in DATA_DIR.iterdir() if d.is_dir() and d.name != "_tmp"])
        if DATA_DIR.exists() else []
    )

    if not res_companies:
        st.info("No results yet. Complete Step 1 (Questionnaire) or Step 3 (LLM MCQ).")
    else:
        res_company_names = [c.name for c in res_companies]
        sel_company_res   = st.selectbox("Select company", res_company_names, key="results_company_select")
        res_dir           = DATA_DIR / sel_company_res / "mcq_answers"
        result_files      = sorted(res_dir.glob("*.json"), reverse=True) if res_dir.exists() else []

        if not result_files:
            st.warning("No MCQ runs found for this company.")
        else:
            sel_file = st.selectbox(
                "Select run", result_files,
                format_func=lambda p: p.name,
                key="results_file_select",
            )
            result  = load_json(sel_file, {})
            answers = result.get("answers", [])

            st.markdown(
                f"**Company:** `{result.get('company')}` · "
                f"**Model:** `{result.get('model', 'manual')}` · "
                f"**Mode:** `{result.get('mode', 'llm')}` · "
                f"**Timestamp:** {result.get('timestamp', '')[:19]}"
            )

            if answers:
                from collections import Counter
                import pandas as pd

                conf_counts = Counter(a.get("confidence", "Unknown") for a in answers)
                c1, c2, c3  = st.columns(3)
                c1.metric("✅ High",   conf_counts.get("High",   0))
                c2.metric("🟡 Medium", conf_counts.get("Medium", 0))
                c3.metric("🔴 Low",    conf_counts.get("Low",    0))

                pillar_filter = st.radio(
                    "Filter by pillar",
                    ["All", "Environmental", "Social", "Governance"],
                    horizontal=True, key="pillar_filter",
                )
                filtered = (
                    answers if pillar_filter == "All"
                    else [a for a in answers if a.get("pillar") == pillar_filter]
                )

                df_res = pd.DataFrame([
                    {
                        "ID":          a.get("id"),
                        "Pillar":      a.get("pillar"),
                        "Question":    (a.get("question", "")[:90] + "…") if len(a.get("question", "")) > 90 else a.get("question", ""),
                        "Selected":    a.get("selected", "—"),
                        "Answer Text": a.get("selected_text", "")[:70],
                        "Confidence":  a.get("confidence", ""),
                        "Evidence":    a.get("evidence", "")[:100],
                    }
                    for a in filtered
                ])
                st.dataframe(df_res, use_container_width=True, height=600)

            st.download_button(
                "⬇️ Download this run (JSON)",
                data=json.dumps(result, ensure_ascii=False, indent=2),
                file_name=sel_file.name,
                mime="application/json",
                key="dl_result",
            )

            if len(result_files) > 1:
                st.divider()
                st.subheader("⚖️ Compare Runs")
                import pandas as pd
                compare_files = st.multiselect(
                    "Select runs to compare",
                    result_files,
                    default=result_files[:2],
                    format_func=lambda p: p.name,
                    key="compare_files",
                )
                if len(compare_files) >= 2:
                    compare_data: dict = {}
                    for cf in compare_files:
                        r = load_json(cf, {})
                        for a in r.get("answers", []):
                            qid = a.get("id")
                            if qid not in compare_data:
                                compare_data[qid] = {"ID": qid, "Question": a.get("question", "")[:60]}
                            compare_data[qid][cf.name[:30]] = a.get("selected", "")
                    st.dataframe(pd.DataFrame(list(compare_data.values())), use_container_width=True)

st.markdown("---")
st.caption("ESG-SME MCQ Verification Pipeline · Mistral OCR + OpenRouter / LM Studio LLM")
"""
7_mcq_verification_clean.py
────────────────────────────────────────────────────────────────────────────────
ESG-SME MCQ Verification Pipeline
────────────────────────────────────────────────────────────────────────────────
Pipeline:
  Step 1 · Upload company PDF(s) → Mistral OCR → save to data/<company_name>/
  Step 2 · Choose a company folder
  Step 3 · Run 1-shot LLM call → answer all 30 ESG-SME MCQs from the OCR text
  Step 4 · Save + display answers; download JSON

Storage layout:
  new_app/data/<company_name>/
      ocr/
          <doc_name>/
              pages/      *.md
              images/     *.jpg …
              ocr_result.json
      mcq_answers/
          <timestamp>_<model>.json
"""

# ── std-lib ────────────────────────────────────────────────────────────────────
import os
import re
import sys
import json
import time
import base64
import zipfile
import tempfile
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
BASE_DIR = Path(__file__).resolve().parents[1]          # new_app/
DATA_DIR = BASE_DIR / "data"                            # new_app/data/
LOG_DIR  = BASE_DIR / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

MISTRAL_API_KEY   = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_BASE      = "https://api.mistral.ai/v1"
MISTRAL_HEADERS   = {"Authorization": f"Bearer {MISTRAL_API_KEY}"}

OPENROUTER_API_URL    = os.getenv("OPENROUTER_API_URL",    "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_MODELS_URL = os.getenv("OPENROUTER_MODELS_URL", "https://openrouter.ai/api/v1/models")
LMSTUDIO_DEFAULT_URL  = "http://localhost:1234/v1"
DEFAULT_OR_MODEL      = "meta-llama/llama-3.1-8b-instruct:free"
BACKEND_OPENROUTER    = "OpenRouter"
BACKEND_LMSTUDIO      = "LM Studio (Local)"

OCR_LOG_FILE = LOG_DIR / "mcq_ocr_log.json"

# ══════════════════════════════════════════════════════════════════════════════
# 30 ESG-SME MCQ QUESTIONS
# ══════════════════════════════════════════════════════════════════════════════
ESG_MCQ: list[dict] = [
    # ── ENVIRONMENTAL (E) ─────────────────────────────────────────────────────
    {
        "id": "E01", "pillar": "Environmental",
        "question": "Does the company track and report its greenhouse gas (GHG) emissions?",
        "choices": {"A": "Yes, Scope 1 and 2", "B": "Yes, Scope 1, 2 and 3",
                    "C": "Partially (informal tracking only)", "D": "No"},
    },
    {
        "id": "E02", "pillar": "Environmental",
        "question": "Has the company set carbon-reduction or net-zero targets?",
        "choices": {"A": "Yes, with a specific year and measurable target",
                    "B": "Yes, but targets are vague / unverified",
                    "C": "Under consideration", "D": "No"},
    },
    {
        "id": "E03", "pillar": "Environmental",
        "question": "Does the company monitor its energy consumption?",
        "choices": {"A": "Yes, with regular reporting", "B": "Yes, but only informally",
                    "C": "Planning to", "D": "No"},
    },
    {
        "id": "E04", "pillar": "Environmental",
        "question": "What share of the company's energy comes from renewable sources?",
        "choices": {"A": ">50 %", "B": "10–50 %", "C": "<10 %", "D": "None / unknown"},
    },
    {
        "id": "E05", "pillar": "Environmental",
        "question": "Does the company have a water-management or water-reduction programme?",
        "choices": {"A": "Yes, with targets", "B": "Yes, informal measures",
                    "C": "Planning to", "D": "No"},
    },
    {
        "id": "E06", "pillar": "Environmental",
        "question": "Does the company measure and manage its waste generation?",
        "choices": {"A": "Yes, with diversion targets (landfill avoidance)",
                    "B": "Yes, general recycling only",
                    "C": "Planning to", "D": "No"},
    },
    {
        "id": "E07", "pillar": "Environmental",
        "question": "Does the company assess its climate-related physical and transition risks?",
        "choices": {"A": "Yes, aligned with TCFD or similar framework",
                    "B": "Yes, basic internal assessment", "C": "Planning to", "D": "No"},
    },
    {
        "id": "E08", "pillar": "Environmental",
        "question": "Does the company have an environmental policy or management system (e.g. ISO 14001)?",
        "choices": {"A": "Yes, certified", "B": "Yes, not certified",
                    "C": "Informal commitments only", "D": "No"},
    },
    {
        "id": "E09", "pillar": "Environmental",
        "question": "Does the company consider environmental factors when selecting suppliers?",
        "choices": {"A": "Yes, formal supplier ESG criteria", "B": "Yes, informal preference",
                    "C": "Planning to", "D": "No"},
    },
    {
        "id": "E10", "pillar": "Environmental",
        "question": "Does the company disclose environmental data in an annual report or sustainability report?",
        "choices": {"A": "Yes, publicly available", "B": "Yes, shared internally only",
                    "C": "Partial disclosure", "D": "No"},
    },
    # ── SOCIAL (S) ────────────────────────────────────────────────────────────
    {
        "id": "S01", "pillar": "Social",
        "question": "Does the company have a formal health & safety (H&S) policy?",
        "choices": {"A": "Yes, with regular audits and KPIs", "B": "Yes, basic policy",
                    "C": "Informal practices", "D": "No"},
    },
    {
        "id": "S02", "pillar": "Social",
        "question": "Does the company track employee injury or accident rates?",
        "choices": {"A": "Yes, reported publicly", "B": "Yes, reported internally",
                    "C": "Partially", "D": "No"},
    },
    {
        "id": "S03", "pillar": "Social",
        "question": "Does the company offer employee training and professional-development programmes?",
        "choices": {"A": "Yes, structured and funded", "B": "Yes, informal / ad-hoc",
                    "C": "Planning to", "D": "No"},
    },
    {
        "id": "S04", "pillar": "Social",
        "question": "Does the company have a diversity, equity & inclusion (DEI) policy?",
        "choices": {"A": "Yes, with targets and reporting", "B": "Yes, general statement only",
                    "C": "Under development", "D": "No"},
    },
    {
        "id": "S05", "pillar": "Social",
        "question": "Does the company measure employee satisfaction or engagement?",
        "choices": {"A": "Yes, regular surveys with action plans", "B": "Yes, informal feedback",
                    "C": "Planning to", "D": "No"},
    },
    {
        "id": "S06", "pillar": "Social",
        "question": "Does the company pay at least the local living wage to all employees?",
        "choices": {"A": "Yes, above living wage", "B": "Yes, at living wage",
                    "C": "Only minimum wage compliance", "D": "Unknown / not disclosed"},
    },
    {
        "id": "S07", "pillar": "Social",
        "question": "Does the company engage with and support local communities?",
        "choices": {"A": "Yes, with dedicated programmes and budget",
                    "B": "Yes, occasional donations/volunteering",
                    "C": "Planning to", "D": "No"},
    },
    {
        "id": "S08", "pillar": "Social",
        "question": "Does the company have a human-rights or fair-labour policy that covers its supply chain?",
        "choices": {"A": "Yes, with audits", "B": "Yes, policy only",
                    "C": "Under development", "D": "No"},
    },
    {
        "id": "S09", "pillar": "Social",
        "question": "Does the company collect and analyse customer satisfaction data?",
        "choices": {"A": "Yes, with structured feedback loops", "B": "Yes, informally",
                    "C": "Planning to", "D": "No"},
    },
    {
        "id": "S10", "pillar": "Social",
        "question": "Does the company provide parental leave or flexible working arrangements?",
        "choices": {"A": "Yes, above statutory minimum", "B": "Yes, at statutory minimum",
                    "C": "Only for certain roles", "D": "No / unknown"},
    },
    # ── GOVERNANCE (G) ────────────────────────────────────────────────────────
    {
        "id": "G01", "pillar": "Governance",
        "question": "Does the company have a board or governance body that oversees ESG issues?",
        "choices": {"A": "Yes, dedicated ESG committee", "B": "Yes, covered by existing board/management",
                    "C": "Planning to", "D": "No"},
    },
    {
        "id": "G02", "pillar": "Governance",
        "question": "Does the company have a formal code of conduct or ethics policy?",
        "choices": {"A": "Yes, published and enforced", "B": "Yes, internal only",
                    "C": "Under development", "D": "No"},
    },
    {
        "id": "G03", "pillar": "Governance",
        "question": "Does the company have an anti-corruption or anti-bribery policy?",
        "choices": {"A": "Yes, with training and controls", "B": "Yes, policy statement only",
                    "C": "Under development", "D": "No"},
    },
    {
        "id": "G04", "pillar": "Governance",
        "question": "Does the company have a whistleblower / speak-up mechanism?",
        "choices": {"A": "Yes, anonymous and independently managed",
                    "B": "Yes, internal channel", "C": "Planning to", "D": "No"},
    },
    {
        "id": "G05", "pillar": "Governance",
        "question": "Does the company have a data-privacy and cybersecurity policy (e.g. GDPR-aligned)?",
        "choices": {"A": "Yes, certified / audited", "B": "Yes, internal policy",
                    "C": "Partial measures", "D": "No"},
    },
    {
        "id": "G06", "pillar": "Governance",
        "question": "Does the company conduct regular financial audits by an independent auditor?",
        "choices": {"A": "Yes, statutory external audit", "B": "Yes, voluntary external audit",
                    "C": "Internal audit only", "D": "No"},
    },
    {
        "id": "G07", "pillar": "Governance",
        "question": "Does the company publicly disclose its ownership structure and key management?",
        "choices": {"A": "Yes, fully transparent", "B": "Partially disclosed",
                    "C": "Available on request", "D": "No"},
    },
    {
        "id": "G08", "pillar": "Governance",
        "question": "Does the company align its ESG reporting with a recognised standard (GRI, SASB, UN SDGs)?",
        "choices": {"A": "Yes, fully aligned", "B": "Partially aligned",
                    "C": "Planning to align", "D": "No"},
    },
    {
        "id": "G09", "pillar": "Governance",
        "question": "Does the company have a formal risk-management framework that covers ESG risks?",
        "choices": {"A": "Yes, integrated into enterprise risk management",
                    "B": "Yes, separate ESG risk register", "C": "Planning to", "D": "No"},
    },
    {
        "id": "G10", "pillar": "Governance",
        "question": "Does the company set measurable ESG targets and report on progress annually?",
        "choices": {"A": "Yes, all three pillars (E, S, G)",
                    "B": "Yes, one or two pillars only",
                    "C": "Targets exist but progress not reported", "D": "No"},
    },
]

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
# ══════════════════════════════════════════════════════════════════════════════
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

    # 1 · Upload
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

    # 2 · Signed URL
    status_fn("🔗 Getting signed URL…")
    r = requests.get(f"{MISTRAL_BASE}/files/{file_id}/url", headers=headers, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Signed URL failed ({r.status_code}): {r.text}")
    signed_url = r.json()["url"]

    # 3 · OCR
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

    # 4 · Save
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
    """Concatenate all page markdown files for a company into a single string."""
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
                     temperature: float = 0.0, max_tokens: int = 100000, retries: int = 3) -> str:
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
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://esg-project.app",
        "X-Title": "ESG MCQ Verifier",
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
        {"id": "meta-llama/llama-3.1-8b-instruct:free",  "label": "Llama 3.1 8B (free)",    "free": True},
        {"id": "meta-llama/llama-3.3-70b-instruct:free",  "label": "Llama 3.3 70B (free)",    "free": True},
        {"id": "mistralai/mistral-7b-instruct:free",       "label": "Mistral 7B (free)",        "free": True},
        {"id": "google/gemma-3-27b-it:free",               "label": "Gemma 3 27B (free)",       "free": True},
        {"id": "deepseek/deepseek-r1:free",                "label": "DeepSeek R1 (free)",       "free": True},
        {"id": "openai/gpt-4o-mini",                       "label": "GPT-4o Mini",              "free": False},
        {"id": "openai/gpt-4o",                            "label": "GPT-4o",                   "free": False},
        {"id": "anthropic/claude-3.5-sonnet",              "label": "Claude 3.5 Sonnet",        "free": False},
        {"id": "anthropic/claude-3.5-haiku",               "label": "Claude 3.5 Haiku",         "free": False},
        {"id": "google/gemini-flash-1.5",                  "label": "Gemini 1.5 Flash",         "free": False},
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
                is_free = float(pricing.get("prompt", 1)) == 0.0 and float(pricing.get("completion", 1)) == 0.0
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
TASK: Answer ALL 30 multiple-choice questions below based STRICTLY on the document text.
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
      "selected": "A",          // letter only
      "selected_text": "...",   // full text of chosen option
      "evidence": "...",        // short quote from document, or "Not found"
      "confidence": "High|Medium|Low"
    }},
    ...  // repeat for all 30 questions
  ]
}}

QUESTIONS:
{q_block}
"""


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════
_DEFAULTS = {
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
st.set_page_config(
    page_title="ESG-SME MCQ Verifier",
    page_icon="📋",
    layout="wide",
)
st.title("📋 ESG-SME MCQ Verification Pipeline")
st.caption(
    "Upload company document(s) → Mistral OCR → 1-shot LLM → "
    "Answer 30 ESG-SME MCQ questions → Save to `data/<company_name>/`"
)

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

    # ── OpenRouter ─────────────────────────────────────────────────────────
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

        tier = st.radio("Filter", ["🆓 Free Only", "💳 Paid Only", "🔀 All"], horizontal=True)
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

    # ── LM Studio ──────────────────────────────────────────────────────────
    else:
        lms_url_input = st.text_input(
            "LM Studio URL", value=st.session_state.lmstudio_url,
            help="Default: http://localhost:1234/v1",
        )
        st.session_state.lmstudio_url = lms_url_input
        lms_models = fetch_lmstudio_models(lms_url_input)

        if lms_models:
            st.success(f"✅ {len(lms_models)} model(s) loaded")
            lms_labels = [m["label"] for m in lms_models]
            curr_lms   = st.session_state.lmstudio_model_id
            def_lms    = lms_labels.index(curr_lms) if curr_lms in lms_labels else 0
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
    temperature  = st.slider("Temperature", 0.0, 1.0, 0.0, 0.01)
    max_tokens   = st.number_input("Max tokens", value=8000, min_value=256, step=256)
    retries      = st.number_input("Retries", value=3, min_value=0, step=1)
    context_chars = st.number_input(
        "OCR context chars sent to LLM", value=15_000, min_value=1000, step=1000,
        help="Truncate OCR text to this many characters before sending to the LLM."
    )

    st.divider()
    if not MISTRAL_API_KEY:
        st.error("❌ MISTRAL_API_KEY not set in .env")
    else:
        st.success("✅ Mistral API key loaded")

# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab_ocr, tab_mcq, tab_results, tab_questions = st.tabs([
    "📤 Step 1 · OCR Upload",
    "🤖 Step 2 · Run MCQ",
    "📊 Step 3 · Results",
    "📋 View All 30 Questions",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 · OCR UPLOAD
# ══════════════════════════════════════════════════════════════════════════════
with tab_ocr:
    st.subheader("📤 Upload Company Documents for OCR")

    company_name_input = st.text_input(
        "Company name (used as folder name)",
        placeholder="e.g. GreenTech_Sdn_Bhd",
        help="A folder will be created at data/<company_name>/",
    )

    uploaded_files = st.file_uploader(
        "Upload PDF(s) or image(s)",
        type=["pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )

    if uploaded_files and company_name_input.strip():
        company_slug = safe_name(company_name_input.strip())
        company_dir  = DATA_DIR / company_slug
        ocr_root     = company_dir / "ocr"

        st.info(
            f"📁 Will save to: `data/{company_slug}/ocr/`\n\n"
            f"Files: {', '.join(f.name for f in uploaded_files)}"
        )

        if not MISTRAL_API_KEY:
            st.error("❌ Cannot run OCR — MISTRAL_API_KEY is not set in `.env`.")
        elif st.button("🚀 Run Bulk OCR", type="primary", use_container_width=True):
            ocr_log = load_json(OCR_LOG_FILE, {})
            progress = st.progress(0)
            total    = len(uploaded_files)

            for i, uploaded in enumerate(uploaded_files, start=1):
                doc_key = f"{company_slug}/{safe_name(uploaded.name)}"
                status  = st.empty()

                if ocr_log.get(doc_key, {}).get("status") == "done":
                    status.warning(f"⏭️ Already processed — skipping: `{uploaded.name}`")
                    progress.progress(i / total)
                    continue

                # Save temp file
                tmp_path = DATA_DIR / "_tmp" / uploaded.name
                tmp_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path.write_bytes(uploaded.getbuffer())

                doc_slug = safe_name(uploaded.name.replace(".", "_"))
                out_dir  = ocr_root / doc_slug

                try:
                    mistral_ocr(tmp_path, out_dir, lambda msg: status.info(f"`{uploaded.name}` · {msg}"))
                    ocr_log[doc_key] = {
                        "status":    "done",
                        "company":   company_slug,
                        "doc":       doc_slug,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                    atomic_write_json(OCR_LOG_FILE, ocr_log)
                    status.success(f"✅ OCR complete: `{uploaded.name}`")
                except Exception as e:
                    ocr_log[doc_key] = {"status": "failed", "error": str(e)}
                    atomic_write_json(OCR_LOG_FILE, ocr_log)
                    status.error(f"❌ OCR failed for `{uploaded.name}`: {e}")

                # Clean up temp
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

                progress.progress(i / total)

            st.session_state.ocr_done = True
            st.success("🎉 Bulk OCR pipeline finished!")

            # ZIP download
            zip_path = DATA_DIR / f"{company_slug}_ocr.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in ocr_root.rglob("*"):
                    if p.is_file():
                        zf.write(p, arcname=p.relative_to(company_dir))
            with open(zip_path, "rb") as zf:
                st.download_button(
                    f"⬇️ Download OCR results ZIP ({company_slug})",
                    data=zf.read(),
                    file_name=f"{company_slug}_ocr.zip",
                    mime="application/zip",
                )

    elif uploaded_files and not company_name_input.strip():
        st.warning("⚠️ Please enter a company name before uploading.")

    # ── Preview existing companies ─────────────────────────────────────────
    st.divider()
    st.subheader("📁 Existing Company Folders")
    companies = sorted([d for d in DATA_DIR.iterdir() if d.is_dir() and d.name != "_tmp"]) if DATA_DIR.exists() else []
    if companies:
        for c in companies:
            docs = list((c / "ocr").iterdir()) if (c / "ocr").exists() else []
            answers = list((c / "mcq_answers").glob("*.json")) if (c / "mcq_answers").exists() else []
            with st.expander(f"🏢 `{c.name}` — {len(docs)} doc(s) · {len(answers)} MCQ run(s)"):
                for d in docs:
                    pages = list((d / "pages").glob("*.md"))
                    st.markdown(f"  - 📄 `{d.name}` — {len(pages)} page(s)")
    else:
        st.info("No company data yet. Upload documents above.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 · RUN MCQ
# ══════════════════════════════════════════════════════════════════════════════
with tab_mcq:
    st.subheader("🤖 Run 30 ESG-SME MCQs (1-shot LLM)")

    companies = sorted([d for d in DATA_DIR.iterdir() if d.is_dir() and d.name != "_tmp"]) if DATA_DIR.exists() else []

    if not companies:
        st.warning("⚠️ No company folders found. Run OCR in Step 1 first.")
    else:
        company_names = [c.name for c in companies]
        selected_company_name = st.selectbox("Select company", company_names, key="mcq_company_select")
        selected_company_dir  = DATA_DIR / selected_company_name

        ocr_text = collect_ocr_text(selected_company_dir)

        if not ocr_text.strip():
            st.warning("⚠️ No OCR text found for this company. Run OCR first.")
        else:
            st.info(
                f"📄 OCR text loaded: ~{len(ocr_text):,} chars · "
                f"Will send first {int(context_chars):,} chars to the LLM."
            )

            with st.expander("👁️ Preview OCR text (first 2 000 chars)", expanded=False):
                st.text(ocr_text[:2000])

            with st.expander("📋 Preview generated prompt (first 3 000 chars)", expanded=False):
                sample_prompt = build_mcq_prompt(selected_company_name, ocr_text, int(context_chars))
                st.text(sample_prompt[:3000])

            st.markdown(f"**Model:** `{active_model}` · **Backend:** {backend}")

            if backend == BACKEND_OPENROUTER and not st.session_state.openrouter_key:
                st.error("❌ OpenRouter API key not set.")
            elif not active_model:
                st.error("❌ No LLM model selected.")
            elif st.button("🚀 Run MCQ Verification (1-shot)", type="primary", use_container_width=True):

                prompt = build_mcq_prompt(selected_company_name, ocr_text, int(context_chars))

                with st.spinner(f"Calling {active_model}…"):
                    try:
                        raw = call_llm(
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
                        ok  = True
                        err = None
                    except Exception as e:
                        raw    = ""
                        parsed = {}
                        ok     = False
                        err    = str(e)

                if ok:
                    st.success("✅ MCQ answers received!")

                    # Enrich parsed with full question metadata for display
                    id_to_q = {q["id"]: q for q in ESG_MCQ}
                    for ans in parsed.get("answers", []):
                        q_meta = id_to_q.get(ans.get("id"), {})
                        if "question" not in ans:
                            ans["question"] = q_meta.get("question", "")
                        if "pillar" not in ans:
                            ans["pillar"] = q_meta.get("pillar", "")
                        # Fill selected_text if missing
                        if "selected_text" not in ans or not ans["selected_text"]:
                            sel = ans.get("selected", "")
                            ans["selected_text"] = q_meta.get("choices", {}).get(sel, "")

                    # Save
                    answers_dir = selected_company_dir / "mcq_answers"
                    answers_dir.mkdir(parents=True, exist_ok=True)
                    ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
                    model_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", active_model)[:40]
                    out_file = answers_dir / f"{ts}_{model_slug}.json"

                    record = {
                        "company":   selected_company_name,
                        "model":     active_model,
                        "backend":   backend,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "ok":        ok,
                        "answers":   parsed.get("answers", []),
                        "raw_output": raw[:5000],
                    }
                    atomic_write_json(out_file, record)
                    st.info(f"💾 Saved to `data/{selected_company_name}/mcq_answers/{out_file.name}`")

                    # Quick summary table
                    st.subheader("📊 Answer Summary")
                    answers = parsed.get("answers", [])
                    if answers:
                        import pandas as pd
                        df = pd.DataFrame([
                            {
                                "ID":         a.get("id"),
                                "Pillar":     a.get("pillar"),
                                "Question":   a.get("question", "")[:80] + "…",
                                "Answer":     a.get("selected"),
                                "Answer Text": a.get("selected_text", "")[:60],
                                "Confidence": a.get("confidence", ""),
                                "Evidence":   a.get("evidence", "")[:80],
                            }
                            for a in answers
                        ])
                        st.dataframe(df, use_container_width=True, height=600)

                    # Download
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
# TAB 3 · RESULTS VIEWER
# ══════════════════════════════════════════════════════════════════════════════
with tab_results:
    st.subheader("📊 MCQ Results Viewer")

    companies = sorted([d for d in DATA_DIR.iterdir() if d.is_dir() and d.name != "_tmp"]) if DATA_DIR.exists() else []

    if not companies:
        st.info("No results yet.")
    else:
        company_names   = [c.name for c in companies]
        sel_company_res = st.selectbox("Select company", company_names, key="results_company_select")
        res_dir         = DATA_DIR / sel_company_res / "mcq_answers"
        result_files    = sorted(res_dir.glob("*.json"), reverse=True) if res_dir.exists() else []

        if not result_files:
            st.warning("No MCQ runs found. Run Step 2 first.")
        else:
            sel_file = st.selectbox(
                "Select run",
                result_files,
                format_func=lambda p: p.name,
                key="results_file_select",
            )
            result = load_json(sel_file, {})
            answers = result.get("answers", [])

            # ── Scorecard ─────────────────────────────────────────────────
            st.markdown(
                f"**Company:** `{result.get('company')}` · "
                f"**Model:** `{result.get('model')}` · "
                f"**Timestamp:** {result.get('timestamp', '')[:19]}"
            )

            # Confidence breakdown
            if answers:
                from collections import Counter
                conf_counts  = Counter(a.get("confidence", "Unknown") for a in answers)
                pillar_sel   = Counter()
                for a in answers:
                    pillar_sel[(a.get("pillar",""), a.get("selected",""))] += 1

                c1, c2, c3 = st.columns(3)
                c1.metric("✅ High confidence",   conf_counts.get("High",   0))
                c2.metric("🟡 Medium confidence", conf_counts.get("Medium", 0))
                c3.metric("🔴 Low confidence",    conf_counts.get("Low",    0))

                # Pillar filter
                pillar_filter = st.radio(
                    "Filter by pillar",
                    ["All", "Environmental", "Social", "Governance"],
                    horizontal=True,
                    key="pillar_filter",
                )
                filtered = answers if pillar_filter == "All" else [
                    a for a in answers if a.get("pillar") == pillar_filter
                ]

                import pandas as pd
                df = pd.DataFrame([
                    {
                        "ID":          a.get("id"),
                        "Pillar":      a.get("pillar"),
                        "Question":    a.get("question", "")[:90] + ("…" if len(a.get("question","")) > 90 else ""),
                        "Selected":    a.get("selected"),
                        "Answer Text": a.get("selected_text", "")[:70],
                        "Confidence":  a.get("confidence", ""),
                        "Evidence":    a.get("evidence", "")[:100],
                    }
                    for a in filtered
                ])
                st.dataframe(df, use_container_width=True, height=600)

            # Download
            st.download_button(
                "⬇️ Download this run (JSON)",
                data=json.dumps(result, ensure_ascii=False, indent=2),
                file_name=sel_file.name,
                mime="application/json",
                key="dl_result",
            )

            # Compare across runs
            if len(result_files) > 1:
                st.divider()
                st.subheader("⚖️ Compare Runs")
                compare_files = st.multiselect(
                    "Select runs to compare",
                    result_files,
                    default=result_files[:2],
                    format_func=lambda p: p.name,
                    key="compare_files",
                )
                if len(compare_files) >= 2:
                    import pandas as pd
                    compare_data = {}
                    for cf in compare_files:
                        r = load_json(cf, {})
                        for a in r.get("answers", []):
                            qid = a.get("id")
                            if qid not in compare_data:
                                compare_data[qid] = {"ID": qid, "Question": a.get("question", "")[:60]}
                            compare_data[qid][cf.name[:30]] = a.get("selected", "")

                    compare_df = pd.DataFrame(list(compare_data.values()))
                    st.dataframe(compare_df, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 · VIEW ALL 30 QUESTIONS
# ══════════════════════════════════════════════════════════════════════════════
with tab_questions:
    st.subheader("📋 All 30 ESG-SME MCQ Questions")

    pillar_filter_q = st.radio(
        "Filter by pillar",
        ["All", "Environmental", "Social", "Governance"],
        horizontal=True,
        key="q_pillar_filter",
    )
    questions_shown = ESG_MCQ if pillar_filter_q == "All" else [
        q for q in ESG_MCQ if q["pillar"] == pillar_filter_q
    ]

    for q in questions_shown:
        with st.expander(f"**{q['id']}** [{q['pillar']}] — {q['question']}", expanded=False):
            for letter, text in q["choices"].items():
                st.markdown(f"- **{letter}.** {text}")

    st.divider()
    st.caption(
        f"Total: {len(ESG_MCQ)} questions · "
        f"E: {sum(1 for q in ESG_MCQ if q['pillar']=='Environmental')} · "
        f"S: {sum(1 for q in ESG_MCQ if q['pillar']=='Social')} · "
        f"G: {sum(1 for q in ESG_MCQ if q['pillar']=='Governance')}"
    )

st.markdown("---")
st.caption("ESG-SME MCQ Verification Pipeline · Mistral OCR + OpenRouter/LM Studio LLM")

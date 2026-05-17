import os
import re
import sys
import time
import json
import socket
import tempfile
import matplotlib
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter, Retry
import streamlit as st
from _page_descriptions import render_page_description

# ── Fix temp directory BEFORE any gradio import ───────────────────────────────
_LOCAL_TMP = Path(__file__).resolve().parents[2] / ".tmp"
_LOCAL_TMP.mkdir(parents=True, exist_ok=True)

def _ensure_tempdir():
    try:
        tempfile.gettempdir()
    except FileNotFoundError:
        os.environ["TMPDIR"]  = str(_LOCAL_TMP)
        os.environ["TEMP"]    = str(_LOCAL_TMP)
        os.environ["TMP"]     = str(_LOCAL_TMP)
        tempfile.tempdir      = str(_LOCAL_TMP)

_ensure_tempdir()

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ── ClimateBERT — lazy import ─────────────────────────────────────────────────
ClimateBERTClient = None
_climatebert_import_error: str = ""

try:
    from api.climatebert_client import ClimateBERTClient as _CB
    ClimateBERTClient = _CB
except Exception as _e:
    _climatebert_import_error = str(_e)

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
OPENROUTER_API_URL    = os.getenv("OPENROUTER_API_URL",    "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_MODELS_URL = os.getenv("OPENROUTER_MODELS_URL", "https://openrouter.ai/api/v1/models")
LMSTUDIO_DEFAULT_URL  = "http://localhost:1234/v1"
DEFAULT_MODEL         = "meta-llama/llama-3.1-8b-instruct:free"
API_KEY_ENV           = "OPENROUTER_API_KEY"
BACKEND_OPENROUTER    = "OpenRouter"
BACKEND_LMSTUDIO      = "LM Studio (Local)"

PROMPT_DIR     = Path(__file__).resolve().parents[1] / "prompt"
OCR_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "thesis_dataset"
RESULTS_DIR    = Path(__file__).resolve().parents[1] / "results"

# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE DEFAULTS
# ══════════════════════════════════════════════════════════════════════════════
_DEFAULTS = {
    "openrouter_key":    os.getenv(API_KEY_ENV, ""),
    "backend":           BACKEND_OPENROUTER,
    "lmstudio_url":      LMSTUDIO_DEFAULT_URL,
    "active_model_id":   DEFAULT_MODEL,
    "lmstudio_model_id": "",
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="ESG Combined Pipeline",
    page_icon="🌿",
    layout="wide",
)
st.title("🌿 ESG Combined Pipeline")
render_page_description(__file__)
st.caption(
    "Run ClimateBERT predictions (T1), ABSA analysis (T2), and "
    "LLM-based ESG structured extraction (T3) — with full-document context."
)

# Show import warning in UI (non-fatal)
if _climatebert_import_error:
    st.warning(
        f"⚠️ **ClimateBERT unavailable** — T1 pipeline will be skipped.\n\n"
        f"`{_climatebert_import_error}`\n\n"
        f"**Fix:** Run `mkdir -p /tmp` in your terminal, or restart the app."
    )

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS — SERIALIZATION
# ══════════════════════════════════════════════════════════════════════════════
def _serialize(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_serialize(o) for o in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    try:
        import numpy as np
        if isinstance(obj, np.ndarray):                return obj.tolist()
        if isinstance(obj, (np.integer, np.floating)): return obj.item()
        if isinstance(obj, np.bool_):                  return bool(obj)
    except ImportError:
        pass
    try:
        import torch
        if isinstance(obj, torch.Tensor):
            return obj.cpu().detach().numpy().tolist()
    except ImportError:
        pass
    if isinstance(obj, Path):     return str(obj)
    if isinstance(obj, datetime): return obj.isoformat()
    if isinstance(obj, matplotlib.figure.Figure): return "<matplotlib.figure.Figure>"
    try:
        import plotly.graph_objs as go
        if isinstance(obj, go.Figure): return obj.to_dict()
    except Exception:
        pass
    if hasattr(obj, "to_dict") and not isinstance(obj, type):
        try:    return obj.to_dict()
        except Exception: pass
    return str(obj)


def make_json_safe(value):
    return _serialize(value)


def append_record(record: dict, fname: Path) -> None:
    """Atomically append one record to a JSON array file."""
    existing: list = []
    if fname.exists():
        try:
            loaded   = json.loads(fname.read_text(encoding="utf-8"))
            existing = loaded if isinstance(loaded, list) else [loaded]
        except Exception:
            existing = []
    existing.append(make_json_safe(record))
    tmp = fname.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(fname)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS — PROMPT
# ══════════════════════════════════════════════════════════════════════════════
def list_prompt_files() -> list[Path]:
    if not PROMPT_DIR.exists():
        return []
    return sorted(PROMPT_DIR.glob("*.md"))


def load_prompt_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def apply_prompt(template: str, input_text: str) -> str:
    if "{{INPUT_TEXT}}" in template:
        return template.replace("{{INPUT_TEXT}}", input_text)
    return template.strip() + f"\n\n---\n\nText to analyze:\n{input_text}"


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS — HTTP / RETRY
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


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS — MODEL FETCHERS
# ══════════════════════════════════════════════════════════════════════════════
def _fallback_openrouter_models() -> list[dict]:
    return [
        {"id": "meta-llama/llama-3.1-8b-instruct:free",  "label": "Llama 3.1 8B",    "free": True,  "notes": "free · 131k ctx",  "ctx": 131072},
        {"id": "meta-llama/llama-3.3-70b-instruct:free",  "label": "Llama 3.3 70B",    "free": True,  "notes": "free · 131k ctx",  "ctx": 131072},
        {"id": "mistralai/mistral-7b-instruct:free",      "label": "Mistral 7B",        "free": True,  "notes": "free · 32k ctx",   "ctx": 32768},
        {"id": "google/gemma-3-27b-it:free",              "label": "Gemma 3 27B",       "free": True,  "notes": "free · 131k ctx",  "ctx": 131072},
        {"id": "deepseek/deepseek-r1:free",               "label": "DeepSeek R1",       "free": True,  "notes": "free · 65k ctx",   "ctx": 65536},
        {"id": "openai/gpt-4o-mini",                      "label": "GPT-4o Mini",       "free": False, "notes": "$0.15/1M · 128k",  "ctx": 128000},
        {"id": "openai/gpt-4o",                           "label": "GPT-4o",            "free": False, "notes": "$2.50/1M · 128k",  "ctx": 128000},
        {"id": "anthropic/claude-3.5-sonnet",             "label": "Claude 3.5 Sonnet", "free": False, "notes": "$3.00/1M · 200k",  "ctx": 200000},
        {"id": "anthropic/claude-3.5-haiku",              "label": "Claude 3.5 Haiku",  "free": False, "notes": "$0.80/1M · 200k",  "ctx": 200000},
        {"id": "google/gemini-flash-1.5",                 "label": "Gemini 1.5 Flash",  "free": False, "notes": "$0.075/1M · 1M",   "ctx": 1000000},
    ]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_openrouter_models(api_key: Optional[str] = None) -> list[dict]:
    if not api_key:
        return _fallback_openrouter_models()
    try:
        resp = requests.get(
            OPENROUTER_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}", "HTTP-Referer": "https://esg-project.app"},
            timeout=10,
        )
        resp.raise_for_status()
        raw    = resp.json().get("data", [])
        models = []
        for m in raw:
            mid     = m.get("id", "")
            name    = m.get("name", mid)
            ctx     = m.get("context_length", 0)
            pricing = m.get("pricing", {})
            try:
                p_cost  = float(pricing.get("prompt", 1))
                c_cost  = float(pricing.get("completion", 1))
                is_free = p_cost == 0.0 and c_cost == 0.0
            except (ValueError, TypeError):
                is_free = str(pricing.get("prompt", "1")) == "0"
            cost_str = "free" if is_free else f"${float(pricing.get('prompt', 0)) * 1_000_000:.3f}/1M"
            ctx_str  = f"{ctx:,} ctx" if ctx else ""
            notes    = " · ".join(filter(None, [cost_str, ctx_str]))
            models.append({"id": mid, "label": name, "free": is_free, "notes": notes, "ctx": ctx})
        models.sort(key=lambda x: (not x["free"], x["label"].lower()))
        return models if models else _fallback_openrouter_models()
    except Exception:
        return _fallback_openrouter_models()


def fetch_lmstudio_models(base_url: str) -> list[dict]:
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/models", timeout=5)
        resp.raise_for_status()
        raw = resp.json().get("data", [])
        return [
            {"id": m.get("id", ""), "label": m.get("id", ""), "free": True,
             "notes": "local · LM Studio", "ctx": m.get("context_length", 4096)}
            for m in raw if m.get("id")
        ]
    except Exception:
        return []



def parse_json_from_model(text: str) -> Any:
    import json, re, ast

    if not text or not text.strip():
        raise ValueError("Empty response from model.")

    text = text.strip()

    # 🔹 Remove markdown code blocks
    text = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).strip("` \n")

    # 🔹 Try direct JSON
    try:
        return json.loads(text)
    except Exception:
        pass

    # 🔹 Extract largest JSON block
    matches = re.findall(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)

    if matches:
        matches = sorted(matches, key=len, reverse=True)
        for m in matches:
            try:
                return json.loads(m)
            except Exception:
                try:
                    return ast.literal_eval(m)
                except Exception:
                    continue

    raise ValueError(f"Could not parse JSON. Raw output:\n{text[:500]}")

def _call_openrouter(prompt: str, model: str, api_key: str,
                     temperature: float = 0.0, max_tokens: int = 1500, retries: int = 3) -> str:

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a strict JSON generator. "
                    "Return ONLY valid JSON. "
                    "Do NOT include markdown, explanations, comments, or text outside JSON. "
                    "If unsure, return an empty JSON list []."
                )
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    s = _requests_session(retries=retries)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://esg-project.app",
        "X-Title": "ESG Extractor",
    }

    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = s.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=90)

            # If client error (4xx) return server body immediately (retries won't help)
            if 400 <= resp.status_code < 500:
                body = resp.text
                raise RuntimeError(f"OpenRouter returned {resp.status_code} Client Error: {body}")

            resp.raise_for_status()
            choices = resp.json().get("choices", [])

            if choices:
                return choices[0].get("message", {}).get("content", "")

            return resp.text

        except RuntimeError:
            # Raise immediately for RuntimeError (e.g. 4xx with server body)
            raise
        except Exception as e:
            last_exc = e
            time.sleep(min(10, 2 ** attempt))

    raise RuntimeError(f"OpenRouter failed after {retries} attempts: {last_exc}")

def _call_lmstudio(prompt: str, model: str, base_url: str,
                   temperature: float = 0.0, max_tokens: int = 1500) -> str:
    url     = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant that outputs strict JSON."},
            {"role": "user",   "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens":  max_tokens,
        "stream":      False,
    }
    if model:
        payload["model"] = model
    resp = requests.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def call_llm(prompt: str, model: str, backend: str, api_key: str = "",
             lmstudio_url: str = LMSTUDIO_DEFAULT_URL,
             temperature: float = 0.0, max_tokens: int = 1500, retries: int = 3) -> str:
    if backend == BACKEND_LMSTUDIO:
        return _call_lmstudio(prompt, model, lmstudio_url, temperature, max_tokens)
    return _call_openrouter(prompt, model, api_key, temperature, max_tokens, retries)


# ══════════════════════════════════════════════════════════════════════════════
# LOAD OPENROUTER MODELS
# ══════════════════════════════════════════════════════════════════════════════
with st.spinner("🔄 Fetching OpenRouter models…"):
    all_or_models = fetch_openrouter_models(st.session_state.openrouter_key or None)

free_models = [m for m in all_or_models if     m["free"]]
paid_models = [m for m in all_or_models if not m["free"]]
id_to_model = {m["id"]: m for m in all_or_models}

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ Global Settings")

    st.subheader("🔀 Pipelines")
    _t1_disabled = ClimateBERTClient is None
    run_t1 = st.checkbox(
        "T1 · ClimateBERT Predictions",
        value=not _t1_disabled,
        disabled=_t1_disabled,
        help="Unavailable — ClimateBERT failed to import" if _t1_disabled else "",
    )
    run_t2 = st.checkbox("T2 · ABSA Analysis",      value=True)
    run_t3 = st.checkbox("T3 · LLM ESG Extraction", value=True)

    st.divider()

    st.subheader("🖥️ LLM Backend (T3)")
    backend = st.radio(
        "Backend",
        [BACKEND_OPENROUTER, BACKEND_LMSTUDIO],
        index=0 if st.session_state.backend == BACKEND_OPENROUTER else 1,
        horizontal=True,
        key="backend_radio",
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
            st.warning("⚠️ No API key — only free/mock mode available")
        if st.button("🔄 Refresh Model List", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        if st.button("🔌 Connectivity Check", use_container_width=True):
            try:
                host = urlparse(OPENROUTER_API_URL).hostname
                addr = socket.getaddrinfo(host, 443)
                st.success(f"DNS OK: {', '.join({ai[4][0] for ai in addr})}")
            except Exception as e:
                st.error(f"DNS issue: {e}")
    else:
        lmstudio_url_input = st.text_input(
            "LM Studio URL", value=st.session_state.lmstudio_url,
            help="Default: http://localhost:1234/v1",
        )
        st.session_state.lmstudio_url = lmstudio_url_input
        lms_models = fetch_lmstudio_models(lmstudio_url_input)
        if lms_models:
            st.success(f"✅ {len(lms_models)} model(s) loaded")
            id_to_model.update({m["id"]: m for m in lms_models})
        else:
            st.error("❌ Cannot reach LM Studio")

    st.divider()

    st.subheader("🤖 LLM Model (T3)")
    if backend == BACKEND_LMSTUDIO:
        lms_models = fetch_lmstudio_models(st.session_state.lmstudio_url)
        if lms_models:
            lms_labels  = [m["label"] for m in lms_models]
            curr_lms    = st.session_state.lmstudio_model_id
            def_idx     = lms_labels.index(curr_lms) if curr_lms in lms_labels else 0
            sel_lms_lbl = st.selectbox(f"Local model ({len(lms_models)} loaded)", lms_labels, index=def_idx)
            sel_lms     = next((m for m in lms_models if m["label"] == sel_lms_lbl), None)
            if sel_lms:
                st.session_state.lmstudio_model_id = sel_lms["id"]
            selected_llm_models = [st.session_state.lmstudio_model_id] if st.session_state.lmstudio_model_id else []
        else:
            st.warning("No local models — load one in LM Studio first.")
            selected_llm_models = []
    else:
        tier = st.radio(
            "Filter:", ["🆓 Free Only", "💳 Paid Only", "🔀 All"],
            horizontal=True, key="model_tier",
        )
        visible = (
            free_models if "Free" in tier else
            paid_models if "Paid" in tier else
            all_or_models
        )
        search = st.text_input("🔍 Search model", placeholder="llama, claude, mistral…")
        if search.strip():
            visible = [m for m in visible if search.lower() in m["label"].lower() or search.lower() in m["id"].lower()]

        visible_labels = [m["label"] for m in visible]
        curr_label     = id_to_model.get(st.session_state.active_model_id, {}).get("label", "")
        def_idx        = visible_labels.index(curr_label) if curr_label in visible_labels else 0

        sel_labels = st.multiselect(
            f"Model(s) ({len(visible)} shown)",
            options=visible_labels,
            default=[visible_labels[def_idx]] if visible_labels else [],
        )
        selected_llm_models = [m["id"] for m in all_or_models if m["label"] in sel_labels]
        if selected_llm_models:
            st.session_state.active_model_id = selected_llm_models[0]
            active_m = id_to_model.get(selected_llm_models[0])
            if active_m:
                badge = "🆓 Free" if active_m["free"] else "💳 Paid"
                st.caption(f"{badge} · {active_m['notes']}\n\n`{active_m['id']}`")

    st.divider()

    st.subheader("⚙️ Generation (T3)")
    temperature_input = st.slider("Temperature", 0.0, 1.0, 0.0, 0.01)
    max_tokens_input  = st.number_input("Max tokens", value=100000, min_value=64, step=100)
    retries_input     = st.number_input("Retries", value=3, min_value=0, step=1)

    st.divider()

    st.subheader("📝 Prompt Template (T3)")
    prompt_files = list_prompt_files()
    # allow selecting multiple prompt templates (order matters)
    selected_prompt_paths: list[Path] = []
    prompt_override = ""
    if not prompt_files:
        st.warning(f"No .md files in `{PROMPT_DIR}`")
    else:
        prompt_names = [p.name for p in prompt_files]
        # default to data.md if present
        default = ["data.md"] if "data.md" in prompt_names else [prompt_names[0]]
        selected_prompt_names = st.multiselect(
            "Select prompt(s) — choose one or more (order matters)",
            prompt_names,
            default=default,
        )
        selected_prompt_paths = [PROMPT_DIR / n for n in selected_prompt_names]

        with st.expander("👁️ Preview selected prompt(s)", expanded=False):
            if not selected_prompt_paths:
                st.markdown("_No prompt selected — default fallback will be used._")
            else:
                for p in selected_prompt_paths:
                    raw_prompt = load_prompt_file(p)
                    st.markdown(f"**{p.name}**")
                    st.markdown(raw_prompt[:1500] + ("…" if len(raw_prompt) > 1500 else ""))

        with st.expander("✏️ Override prompt (optional)", expanded=False):
            st.caption("Use `{{INPUT_TEXT}}` as placeholder. Leave blank to use file(s).")
            prompt_override = st.text_area(
                "Custom prompt",
                value="",
                height=150,
                placeholder="Leave blank to use the selected file(s)…",
            )

    st.divider()

    st.subheader("💾 Output")
    save_t1     = st.checkbox("Save T1 predictions",       value=True)
    save_t2     = st.checkbox("Save T2 ABSA results",      value=True)
    save_t3     = st.checkbox("Save T3 ESG records",       value=True)
    use_mock_t3 = st.checkbox("Mock T3 (offline testing)", value=False)
    run_deep_model = st.checkbox("Run Deep Model in T2 (slow)", value=False)

    st.divider()
    st.subheader("🛠️ System")
    try:
        _td = tempfile.gettempdir()
        st.success(f"✅ Temp dir: `{_td}`")
    except Exception as _te:
        st.error(f"❌ Temp dir broken: {_te}\n\nFallback: `{_LOCAL_TMP}`")
    if st.button("🔧 Fix temp dir", use_container_width=True):
        _ensure_tempdir()
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# INPUT SOURCE
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("📥 Input Source")
context_length = st.slider(
    "Context length (characters to send to LLM)", 
    min_value=500, max_value=100_000, value=10_000, step=500,
    help="Controls how much of the document is sent as context to the LLM. Increase for more context, decrease for shorter prompts."
)

input_mode = st.radio(
    "Mode", ["Manual text", "OCR document"],
    horizontal=True,
    key="input_mode_radio",
)

texts_to_process:    list[dict] = []
doc_full_text:       str        = ""
selected_page_texts: list[dict] = []
all_page_files:      list       = []

if input_mode == "Manual text":
    manual_text = st.text_area("Enter text to analyze", height=200, key="manual_text_area")
    if manual_text.strip():
        t = manual_text.strip()
        texts_to_process    = [{"label": "manual_input", "text": t}]
        selected_page_texts = texts_to_process
        doc_full_text       = t
        all_page_files      = []

else:
    doc_folders = sorted(
        [d for d in OCR_OUTPUT_DIR.iterdir() if d.is_dir()],
        key=lambda d: d.name,
    ) if OCR_OUTPUT_DIR.exists() else []

    if not doc_folders:
        st.warning(f"No document folders found in `{OCR_OUTPUT_DIR}`")
    else:
        doc_names    = [d.name for d in doc_folders]
        selected_doc = st.selectbox("Select document", doc_names, key="doc_select")
        pages_dir    = OCR_OUTPUT_DIR / selected_doc / "pages"
        all_page_files = sorted(pages_dir.glob("*.md")) if pages_dir.exists() else []

        if not all_page_files:
            st.warning(f"No `.md` page files in `{pages_dir}`")
        else:
            page_names = [p.name for p in all_page_files]

            doc_full_text = "\n\n".join(
                pf.read_text(encoding="utf-8").strip()
                for pf in all_page_files
                if pf.read_text(encoding="utf-8").strip()
            )

            st.info(
                f"📄 **Full document**: {len(all_page_files)} page(s) · "
                f"~{len(doc_full_text):,} chars loaded as LLM context"
            )

            st.markdown("#### 📑 Select pages for sentence-level extraction")
            st.caption(
                "The **full document** is always sent to the LLM as context. "
                "Use this to focus extraction on specific pages."
            )

            selection_mode = st.radio(
                "Page selection", ["All pages", "Select specific pages"],
                horizontal=True,
                key="page_selection_radio",
            )

            if selection_mode == "All pages":
                chosen_pages = all_page_files
            else:
                chosen_names = st.multiselect(
                    "Select page(s)", page_names,
                    default=[page_names[0]],
                    key="page_multiselect",
                )
                chosen_pages = [pages_dir / n for n in chosen_names]

                # Add batch size selector
                batch_size = st.number_input(
                    "Batch size (pages per group)", min_value=1, max_value=len(chosen_pages), value=2, step=1
                )

                # Split chosen_pages into batches
                def batch_pages(pages, size):
                    return [pages[i:i+size] for i in range(0, len(pages), size)]

                page_batches = batch_pages(chosen_pages, batch_size)

                st.info(f"Processing {len(page_batches)} batch(es) of {batch_size} page(s) each.")

                # Preview batches
                with st.expander("Preview batches", expanded=False):
                    for idx, batch in enumerate(page_batches, 1):
                        st.markdown(f"**Batch {idx}:** {[p.name for p in batch]}")

                # Process ALL batches (recursively) — create one texts_to_process entry per batch
                texts_to_process = [
                    {
                        "label": f"{selected_doc}/batch_{idx+1}",
                        "text": "\n\n".join(p.read_text(encoding="utf-8").strip() for p in batch if p.read_text(encoding="utf-8").strip())
                    }
                    for idx, batch in enumerate(page_batches)
                ]

                # Also expose for components that expect selected_page_texts (a list of page-like dicts)
                # For batch-level processing we keep selected_page_texts as the flattened pages of the first batch
                selected_page_texts = [
                    {"label": f"{selected_doc}/{p.name}", "text": p.read_text(encoding="utf-8").strip()}
                    for p in page_batches[0]
                    if p.read_text(encoding="utf-8").strip()
                ]
# RUN SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
if texts_to_process:
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Pages selected",   len(texts_to_process))
    col_b.metric("LLM models (T3)",  len(selected_llm_models))
    col_c.metric("Pipelines active", sum([run_t1, run_t2, run_t3]))

    if run_t3 and selected_llm_models and doc_full_text:
        with st.expander("📋 T3 run plan", expanded=False):
            st.markdown(
                f"**Context:** full document (~{len(doc_full_text):,} chars)\n\n"
                f"**Sentence capture pages:** {len(texts_to_process)}"
            )
            for m in selected_llm_models:
                m_info = id_to_model.get(m, {})
                st.markdown(f"- **{m_info.get('label', m)}** · `{m}`")

# ══════════════════════════════════════════════════════════════════════════════
# EXECUTE BUTTON
# ══════════════════════════════════════════════════════════════════════════════
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

if st.button("🚀 Run Selected Pipelines", type="primary", use_container_width=True):
    if not texts_to_process:
        st.warning("⚠️ No text selected. Enter text or select pages above.")
        st.stop()
    if not any([run_t1, run_t2, run_t3]):
        st.warning("⚠️ No pipelines selected in sidebar.")
        st.stop()

    # ─────────────────────────────────────────────────────────────────────────
    # T1 · ClimateBERT
    # ─────────────────────────────────────────────────────────────────────────
    if run_t1:
        st.markdown("---")
        st.subheader("📊 T1 · ClimateBERT Predictions")

        if ClimateBERTClient is None:
            st.error(
                f"❌ ClimateBERT is not available.\n\n`{_climatebert_import_error}`\n\n"
                "**Quick fix:**\n```bash\nsudo mkdir -p /tmp && sudo chmod 1777 /tmp\n```"
            )
        else:
            try:
                api       = ClimateBERTClient()
                cb_models = api.available_models if hasattr(api, "available_models") else []
            except Exception as e:
                st.error(f"ClimateBERT client init failed: {e}")
                cb_models = []

            if not cb_models:
                st.warning("No ClimateBERT models available.")
            else:
                t1_results  = []
                t1_fname    = RESULTS_DIR / "predictions.json"
                t1_progress = st.progress(0)
                t1_total    = len(texts_to_process) * len(cb_models)
                t1_step     = 0

                for item in texts_to_process:
                    for model_key in cb_models:
                        with st.spinner(f"T1 · [{item['label']}] {model_key}…"):
                            try:
                                res     = api.predict(text=item["text"], model_key=model_key)
                                outcome = "✅ ok"
                            except Exception as e:
                                res     = {"error": str(e)}
                                outcome = f"⚠️ {e}"

                            record = {
                                "timestamp": datetime.utcnow().isoformat() + "Z",
                                "model":     model_key,
                                "source":    item["label"],
                                "text":      item["text"],
                                "result":    res,
                            }
                            t1_results.append(record)

                            # ── immediate save after every single record ──
                            if save_t1:
                                try:
                                    append_record(record, t1_fname)
                                    st.caption(f"💾 saved `{model_key}` / `{item['label']}`")
                                except Exception as save_err:
                                    st.warning(f"⚠️ T1 save failed: {save_err}")

                            st.write(f"`{item['label']}` × `{model_key}` → {outcome}")
                        t1_step += 1
                        t1_progress.progress(t1_step / t1_total)

                t1_progress.empty()
                st.success(f"T1 complete · {len(t1_results)} prediction(s)")

                with st.expander("📊 T1 Results JSON", expanded=False):
                    st.json(t1_results)

                if save_t1:
                    st.info(f"💾 T1 records appended live to `{t1_fname}`")

                st.download_button(
                    "⬇️ Download T1 predictions (JSON)",
                    json.dumps([make_json_safe(r) for r in t1_results], ensure_ascii=False, indent=2),
                    file_name=f"predictions_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json",
                    mime="application/json",
                    key="dl_t1",
                )

    # ─────────────────────────────────────────────────────────────────────────
    # T2 · ABSA  (saves immediately after each page)
    # ─────────────────────────────────────────────────────────────────────────
    if run_t2:
        st.markdown("---")
        st.subheader("🧠 T2 · ABSA Analysis")
        try:
            from code.rule_based import collect_aspects, polarity_basic, tone_basic
            from code.hybrid_model import run_hierarchical_hybrid
            from code.explainability import compare_explain
            absa_imports_ok = True
        except ImportError as e:
            st.error(f"❌ ABSA import failed: {e}")
            absa_imports_ok = False

        if absa_imports_ok:
            t2_fname       = RESULTS_DIR / "absa_results.json"
            all_t2_records = []
            t2_progress    = st.progress(0)
            t2_total       = len(texts_to_process)

            for idx, item in enumerate(texts_to_process):
                text_input = item["text"]
                label      = item["label"]

                st.divider()
                st.markdown(f"#### 📄 `{label}`")

                rb_out = cml_out = hybrid_out = expl_out = {}
                deep_out = {"ran": run_deep_model}

                with st.expander("🔧 Rule-Based", expanded=False):
                    try:
                        aspects  = collect_aspects(text_input)
                        polarity = polarity_basic(text_input)
                        tone     = tone_basic(text_input)
                        st.write(f"**Aspects:** {aspects}")
                        st.write(f"**Polarity:** {polarity}")
                        st.write(f"**Tone:** {tone}")
                        rb_out = {"aspects": aspects, "polarity": polarity, "tone": tone}
                    except Exception as e:
                        st.error(f"Rule-based error: {e}")
                        rb_out = {"error": str(e)}

                with st.expander("📐 Classical ML", expanded=False):
                    try:
                        from code.classical_ml import run_classical_ml
                        _, out_df, _, coef_sent, coef_aspect = run_classical_ml(text_input)
                        st.dataframe(out_df,      use_container_width=True)
                        st.dataframe(coef_sent,   use_container_width=True)
                        st.dataframe(coef_aspect, use_container_width=True)
                        cml_out = {"out_df": out_df, "coef_sent": coef_sent, "coef_aspect": coef_aspect}
                    except Exception as e:
                        st.error(f"Classical ML error: {e}")
                        cml_out = {"error": str(e)}

                with st.expander("🧬 Deep Model (mBERT)", expanded=False):
                    if run_deep_model:
                        try:
                            from code.deep_model import run_deep_learning
                            _, deep_df, _, interp_df = run_deep_learning(text_input)
                            st.dataframe(deep_df,   use_container_width=True)
                            st.dataframe(interp_df, use_container_width=True)
                            deep_out.update({"out_df": deep_df, "interpretability": interp_df})
                        except Exception as e:
                            st.error(f"Deep model error: {e}")
                            deep_out["error"] = str(e)
                    else:
                        st.info("Skipped — enable 'Run Deep Model' in sidebar.")

                with st.expander("🔀 Hybrid Model", expanded=False):
                    try:
                        _, hybrid_df, _, _, _, metrics = run_hierarchical_hybrid(text_input)
                        st.dataframe(hybrid_df, use_container_width=True)
                        st.write("**Metrics:**", metrics)
                        # ── always store as list-of-dicts so highlight viewer can iterate ──
                        hybrid_out = {
                            "out_df":  hybrid_df.to_dict(orient="records") if hasattr(hybrid_df, "to_dict") else hybrid_df,
                            "metrics": metrics.to_dict(orient="records")   if hasattr(metrics,   "to_dict") else metrics,
                        }
                    except Exception as e:
                        st.error(f"Hybrid model error: {e}")
                        hybrid_out = {"error": str(e)}

                with st.expander("💡 Explainability", expanded=False):
                    try:
                        expl_df, expl_fig, expl_scatter = compare_explain()
                        st.dataframe(expl_df, use_container_width=True)
                        if expl_fig:                  st.pyplot(expl_fig)
                        if expl_scatter is not None:  st.plotly_chart(expl_scatter)
                        expl_out = {"compare_df": expl_df}
                    except Exception as e:
                        st.error(f"Explainability error: {e}")
                        expl_out = {"error": str(e)}

                record = {
                    "timestamp":      datetime.utcnow().isoformat() + "Z",
                    "source":         label,
                    "input_text":     text_input,
                    "rule_based":     rb_out,
                    "classical_ml":   cml_out,
                    "deep_model":     deep_out,
                    "hybrid_model":   hybrid_out,
                    "explainability": expl_out,
                }
                all_t2_records.append(record)

                # ── immediate save after each page ──
                if save_t2:
                    try:
                        append_record(record, t2_fname)
                        st.caption(f"💾 T2 saved `{label}`")
                    except Exception as save_err:
                        st.error(f"T2 save failed for `{label}`: {save_err}")

                t2_progress.progress((idx + 1) / t2_total)

            t2_progress.empty()
            st.success(f"T2 complete · {len(all_t2_records)} document(s) processed")
            if save_t2:
                st.info(f"💾 T2 records appended live to `{t2_fname}`")

            st.download_button(
                "⬇️ Download T2 ABSA results (JSON)",
                json.dumps([make_json_safe(r) for r in all_t2_records], ensure_ascii=False, indent=2),
                file_name=f"absa_results_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json",
                mime="application/json",
                key="dl_t2",
            )

    # ─────────────────────────────────────────────────────────────────────────
    # T3 · LLM ESG Extraction  (saves immediately after each model)
    # ─────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────
# T3 · LLM ESG Extraction (FIXED VERSION)
# ─────────────────────────────────────────────────────────────────────────
    if run_t3:
        st.markdown("---")
        st.subheader("🌿 T3 · LLM ESG Structured Extraction")

        if not selected_llm_models:
            st.warning("⚠️ No LLM model selected for T3.")
        elif not doc_full_text:
            st.warning("⚠️ No document text available.")
        elif backend == BACKEND_OPENROUTER and not use_mock_t3 and not st.session_state.openrouter_key:
            st.error("❌ OpenRouter API key not set.")
        else:

            if selected_prompt_paths:
                plabels = ", ".join(p.name for p in selected_prompt_paths)
                st.info(f"📝 Prompt(s): **{plabels}**")
            else:
                st.info("📝 Prompt(s): default fallback")

            def build_context_prompt(full_doc: str, page_texts: list[dict], template: str) -> str:
                # Respect the context_length slider to avoid sending huge prompts that cause 400 errors
                trimmed_doc = full_doc[:context_length] if context_length and len(full_doc) > context_length else full_doc
                if len(full_doc) > len(trimmed_doc):
                    trimmed_note = f"\n\n[NOTE: full document truncated to {len(trimmed_doc):,} chars of {len(full_doc):,} total]"
                else:
                    trimmed_note = ""

                page_section = "\n\n---\n\n".join(
                    f"[PAGE: {p['label']}]\n{p['text']}" for p in page_texts
                )

                combined = (
                    f"FULL DOCUMENT:\n{trimmed_doc}{trimmed_note}\n\n"
                    f"TARGET PAGES:\n{page_section}\n\n"
                    f"Return JSON array of ESG records."
                )

                return apply_prompt(template, combined)

            t3_fname = RESULTS_DIR / "esg_records.json"
            all_t3_records = []

            # --- Load existing records so we can resume and avoid re-running successful items
            existing_records = []
            if t3_fname.exists():
                try:
                    existing_records = json.loads(t3_fname.read_text(encoding="utf-8")) or []
                except Exception:
                    existing_records = []

            # build set of successfully completed (model, target, prompt) triples to skip on resume
            processed_success = {
                (r.get("model"), r.get("target"), r.get("prompt")) for r in existing_records if r.get("ok")
            }

            # present combined results in-memory (existing + new)
            all_t3_records.extend(existing_records)

            # progress is now total runs = models * batches * prompts
            n_models = len(selected_llm_models) if selected_llm_models else 1
            n_batches = max(1, len(texts_to_process))
            n_prompts = max(1, len(selected_prompt_paths) if selected_prompt_paths else 1)
            t3_total = max(1, n_models * n_batches * n_prompts)
            t3_progress = st.progress(0)
            t3_step = 0

            for i, model in enumerate(selected_llm_models, 1):

                m_info = id_to_model.get(model, {})
                st.info(f"⏳ Running model: {model} ({i}/{len(selected_llm_models)})")

                # iterate over all batches / target items
                for b_idx, target in enumerate(texts_to_process, 1):

                    # iterate over selected prompts (or single default fallback)
                    prompt_paths = selected_prompt_paths or []
                    if not prompt_paths:
                        # keep a single None to indicate default fallback usage later
                        prompt_paths = [None]

                    for p_idx, prompt_path in enumerate(prompt_paths, 1):
                        # determine prompt text & label
                        if prompt_override.strip():
                            base_prompt = prompt_override.strip()
                            prompt_label = "override"
                        elif prompt_path is None:
                            base_prompt = "You are an ESG expert. Analyze:\n{{INPUT_TEXT}}\nOutput a JSON list of ESG records."
                            prompt_label = "default_fallback"
                        else:
                            try:
                                base_prompt = load_prompt_file(prompt_path)
                            except Exception:
                                base_prompt = "You are an ESG expert. Analyze:\n{{INPUT_TEXT}}\nOutput a JSON list of ESG records."
                            prompt_label = prompt_path.name

                        # Skip if already completed successfully in a previous run
                        if (model, target["label"], prompt_label) in processed_success:
                            st.info(f"⏭️ Skipping already-successful: {model} · {target['label']} · {prompt_label}")
                            t3_step += 1
                            t3_progress.progress(t3_step / t3_total)
                            continue

                        final_prompt = build_context_prompt(doc_full_text, [ {"label": target["label"], "text": target["text"]} ], base_prompt)

                        try:
                            if use_mock_t3:
                                raw_output = json.dumps([
                                    {"text": "mock", "esg": "Environmental", "sentiment": "Positive", "source": target["label"]}
                                ])
                            else:
                                raw_output = call_llm(
                                    prompt=final_prompt,
                                    model=model,
                                    backend=backend,
                                    api_key=st.session_state.openrouter_key,
                                    lmstudio_url=st.session_state.lmstudio_url,
                                    temperature=float(temperature_input),
                                    max_tokens=int(max_tokens_input),
                                    retries=int(retries_input),
                                )

                            # 🔍 DEBUG OUTPUT
                            with st.expander(f"🧪 Raw Output — {model} — {target['label']} — {prompt_label}"):
                                st.code(raw_output)

                            # ✅ SAFE PARSING
                            try:
                                parsed = parse_json_from_model(raw_output)

                                if isinstance(parsed, dict):
                                    parsed = [parsed]
                                elif not isinstance(parsed, list):
                                    parsed = []

                                ok = True
                                err = None

                            except Exception as parse_err:
                                parsed = []
                                ok = False
                                err = f"Parse error: {parse_err}"

                        except Exception as e:
                            parsed = []
                            ok = False
                            err = str(e)
                            raw_output = ""

                        # include raw_output (truncated) and prompt_label to help resume/debug
                        record = {
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                            "model": model,
                            "target": target["label"],
                            "prompt": prompt_label,
                            "ok": ok,
                            "records": parsed,
                            **({"error": err} if err else {}),
                            "raw_output": (raw_output[:10000] if raw_output else ""),
                        }

                        all_t3_records.append(record)

                        if ok:
                            st.success(f"✅ {model} · {target['label']} · {prompt_label} → {len(parsed)} records")
                            st.json(parsed)
                        else:
                            st.error(f"❌ {model} · {target['label']} · {prompt_label} failed: {err}")

                        # 💾 ALWAYS SAVE IMMEDIATELY (success OR failure) so we can resume later
                        if save_t3:
                            try:
                                append_record(record, t3_fname)
                                if ok:
                                    st.caption(f"💾 Saved: {model} · {target['label']} · {prompt_label}")
                                else:
                                    st.warning(f"💾 Saved partial/failed result: {model} · {target['label']} · {prompt_label} (error stored)")
                            except Exception as save_err:
                                st.warning(f"Save failed: {save_err}")

                        t3_step += 1
                        t3_progress.progress(t3_step / t3_total)

            t3_progress.empty()

            st.success("🎉 T3 Completed")

            st.download_button(
                "⬇️ Download T3 JSON",
                json.dumps(all_t3_records, indent=2, ensure_ascii=False),
                file_name="t3_results.json",
                mime="application/json",
            )

    st.markdown("---")
    st.caption("ESG Combined Pipeline · T1 ClimateBERT · T2 ABSA · T3 LLM Extraction")

import streamlit as st
import os
import requests
from dotenv import load_dotenv
from pathlib import Path
import zipfile
import shutil
import base64
import time
import json
import re

# =====================================================
# PATH & ENV
# =====================================================

BASE_DIR = Path(__file__).parents[1]
load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("MISTRAL_API_KEY")
if not API_KEY:
    st.error("❌ MISTRAL_API_KEY not found in .env")
    st.stop()

BASE = "https://api.mistral.ai/v1"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

TMP_DIR = BASE_DIR / "data" / "thesis_pdf" # / "tmp_upload"
OUT_DIR = BASE_DIR / "data" / "thesis_dataset" # / "outputs"
LOG_DIR = BASE_DIR / "logs"

TMP_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "bulk_ocr_log.json"

# =====================================================
# STREAMLIT CONFIG
# =====================================================

st.set_page_config(page_title="📚 Bulk OCR — Mistral", layout="wide")
st.title("📚 Bulk OCR Pipeline — Mistral OCR")

st.markdown("""
### Pipeline
1. Upload multiple PDFs / images  
2. Upload to Mistral  
3. Get signed URL  
4. Run OCR  
5. Save pages + images + full JSON per document  
6. Resume-safe (skip processed)  
7. Download all as ZIP  
""")

# =====================================================
# UTIL
# =====================================================

def safe_name(name: str) -> str:
    """Sanitize a filename to be safe for all OS."""
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def safe_image_name(raw_id: str, fallback: str) -> str:
    """
    Sanitize an image ID from Mistral into a valid filename.
    Keeps the extension if present, strips all path components.
    """
    # Take only the last component (after any / or \)
    base = re.split(r"[/\\]", raw_id)[-1]
    # Replace any remaining invalid chars
    base = re.sub(r'[\\/*?:"<>|]', "_", base).strip()
    if not base:
        base = fallback
    # Ensure it has a valid image extension
    if not re.search(r"\.(jpg|jpeg|png|gif|webp|bmp)$", base, re.IGNORECASE):
        base += ".jpg"
    return base

def load_log():
    if LOG_FILE.exists():
        return json.loads(LOG_FILE.read_text())
    return {}

def save_log(log):
    LOG_FILE.write_text(json.dumps(log, indent=2))

# =====================================================
# FILE UPLOAD
# =====================================================

uploaded_files = st.file_uploader(
    "📤 Upload multiple thesis PDFs or scanned images",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files=True,
)

if "ocr_done" not in st.session_state:
    st.session_state["ocr_done"] = False

if uploaded_files:

    st.success(f"Uploaded {len(uploaded_files)} file(s)")

    if st.button("🚀 Run BULK OCR Pipeline"):

        st.session_state["ocr_done"] = False

        TMP_DIR.mkdir(exist_ok=True)
        OUT_DIR.mkdir(exist_ok=True)

        log = load_log()

        progress = st.progress(0)
        status = st.empty()

        total = len(uploaded_files)

        for i, uploaded in enumerate(uploaded_files, start=1):

            doc_key = safe_name(uploaded.name)

            status.info(f"Processing {i}/{total}: {uploaded.name}")

            if doc_key in log and log[doc_key]["status"] == "done":
                status.warning(f"⏭ Skipped (already processed): {uploaded.name}")
                progress.progress(i / total)
                continue

            # ---------------- Save temp file ----------------
            tmp_path = TMP_DIR / uploaded.name
            tmp_path.write_bytes(uploaded.getbuffer())

            doc_name = safe_name(uploaded.name.replace(".", "_"))
            out_root = OUT_DIR / doc_name
            pages_dir = out_root / "pages"
            images_dir = out_root / "images"
            pages_dir.mkdir(parents=True, exist_ok=True)
            images_dir.mkdir(parents=True, exist_ok=True)

            try:
                # ---------------- Upload ----------------
                with open(tmp_path, "rb") as f:
                    r = requests.post(
                        f"{BASE}/files",
                        headers=HEADERS,
                        files={"file": (tmp_path.name, f)},
                        data={"purpose": "ocr"},
                        timeout=120,
                    )
                if r.status_code != 200:
                    raise RuntimeError(f"Upload failed: {r.text}")
                file_id = r.json()["id"]

                # ---------------- Signed URL ----------------
                r = requests.get(
                    f"{BASE}/files/{file_id}/url",
                    headers=HEADERS,
                    timeout=60,
                )
                if r.status_code != 200:
                    raise RuntimeError(f"Signed URL failed: {r.text}")
                signed_url = r.json()["url"]

                # ---------------- OCR ----------------
                payload = {
                    "model": "mistral-ocr-latest",
                    "document": {
                        "type": "document_url",
                        "document_url": signed_url,
                    },
                    "include_image_base64": True,
                }

                r = requests.post(
                    f"{BASE}/ocr",
                    headers={**HEADERS, "Content-Type": "application/json"},
                    json=payload,
                    timeout=300,
                )
                if r.status_code != 200:
                    raise RuntimeError(f"OCR failed: {r.text}")

                result = r.json()

                # ---------------- Save Complete JSON Output ----------------
                json_path = out_root / "ocr_result.json"
                json_path.write_text(
                    json.dumps(result, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )

                # ---------------- Save Pages & Images ----------------
                pages = result.get("pages", [])
                img_counter = 0  # global counter per doc for unique fallback names

                for p in pages:
                    idx = p.get("index", 0)
                    md = p.get("markdown", "")

                    (pages_dir / f"page_{idx:04d}.md").write_text(md, encoding="utf-8")

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
                            st.warning(f"⚠ Could not decode image on page {idx}, skipping.")
                            continue

                        raw_id = img.get("id", "")
                        fallback = f"page{idx:04d}_img{img_counter:04d}.jpg"
                        img_name = safe_image_name(raw_id, fallback) if raw_id else fallback
                        img_counter += 1

                        img_path = images_dir / img_name
                        img_path.write_bytes(img_bytes)

                log[doc_key] = {
                    "status": "done",
                    "pages": len(pages),
                    "json_output": str(json_path),
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                save_log(log)

            except Exception as e:
                log[doc_key] = {"status": "failed", "error": str(e)}
                save_log(log)
                st.error(f"❌ Failed: {uploaded.name}")
                st.exception(e)

            progress.progress(i / total)
            time.sleep(0.2)

        status.success("✅ Bulk OCR completed!")
        st.session_state["ocr_done"] = True

# =================================================
# OUTPUT DOWNLOAD
# =================================================

if st.session_state.get("ocr_done") and OUT_DIR.exists() and any(OUT_DIR.iterdir()):

    zip_path = BASE_DIR / "bulk_ocr_outputs.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in OUT_DIR.rglob("*"):
            try:
                if p.is_file() and p.exists():
                    z.write(p, arcname=p.relative_to(OUT_DIR))
            except FileNotFoundError:
                pass

    with open(zip_path, "rb") as f:
        st.download_button(
            "⬇ Download ALL OCR Results (ZIP)",
            data=f,
            file_name="bulk_ocr_outputs.zip",
            mime="application/zip",
        )

    st.divider()

    # =================================================
    # PREVIEW
    # =================================================

    st.subheader("🔍 Preview OCR Output")

    docs = sorted([p for p in OUT_DIR.iterdir() if p.is_dir()])

    if docs:
        doc = st.selectbox("Select document", docs, format_func=lambda p: p.name)

        pages = sorted((doc / "pages").glob("*.md"))
        images = sorted((doc / "images").glob("*"))

        # Show JSON download per document
        json_file = doc / "ocr_result.json"
        if json_file.exists():
            with open(json_file, "rb") as jf:
                st.download_button(
                    f"⬇ Download JSON for {doc.name}",
                    data=jf,
                    file_name=f"{doc.name}_ocr_result.json",
                    mime="application/json",
                )

        if pages:
            page = st.selectbox(
                "Select page",
                pages,
                format_func=lambda p: p.name,
            )

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("### OCR Text")
                st.text_area(
                    "",
                    value=page.read_text(encoding="utf-8", errors="ignore"),
                    height=500,
                )

            with col2:
                st.markdown("### Images")
                if images:
                    for img in images:
                        try:
                            st.image(str(img), use_container_width=True)
                        except Exception as e:
                            st.warning(f"⚠ Cannot display `{img.name}`: {e}")
                else:
                    st.info("No images extracted for this document.")
    else:
        st.info("No OCR results yet.")

import streamlit as st
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
import requests
import pandas as pd
import streamlit.components.v1 as components

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Pear AI Chatbot",
    page_icon="🤖",
    layout="wide",
)

# ── Constants ──────────────────────────────────────────────────────────────────
# Point to the news_collection/data folder (two levels up from new_app/pages/)
DATA_DIR         = Path(__file__).parent.parent.parent / "data"
CHAT_HISTORY_DIR = Path(__file__).parent.parent / "data" / "chat_history"
CHAT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_CONTEXT_CHARS  = 12_000
CHUNK_PREVIEW_LEN  = 300


# ══════════════════════════════════════════════════════════════════════════════
# API KEY
# ══════════════════════════════════════════════════════════════════════════════

def _get_api_key() -> str:
    # 1. Session state (user typed it in)
    if st.session_state.get("api_key", "").strip():
        return st.session_state["api_key"].strip()
    # 2. Env / .env fallback
    try:
        from config.settings import settings
        for attr in ("OPENROUTER_API_KEY", "openrouter_api_key", "api_key"):
            val = getattr(settings, attr, None)
            if val and str(val).strip():
                return str(val).strip()
    except Exception:
        pass
    return os.getenv("OPENROUTER_API_KEY", "")


# ══════════════════════════════════════════════════════════════════════════════
# OPENROUTER MODEL FETCHER  (ported from grading_lab.py)
# ══════════════════════════════════════════════════════════════════════════════

def _FALLBACK_MODELS() -> list[dict]:
    return [
        {"id": "meta-llama/llama-3.1-8b-instruct:free",   "label": "Llama 3.1 8B",       "free": True,  "notes": "free · 131,072 ctx", "ctx": 131072},
        {"id": "meta-llama/llama-3.3-70b-instruct:free",   "label": "Llama 3.3 70B",       "free": True,  "notes": "free · 131,072 ctx", "ctx": 131072},
        {"id": "mistralai/mistral-7b-instruct:free",       "label": "Mistral 7B",           "free": True,  "notes": "free · 32,768 ctx",  "ctx": 32768},
        {"id": "google/gemma-3-27b-it:free",               "label": "Gemma 3 27B",          "free": True,  "notes": "free · 131,072 ctx", "ctx": 131072},
        {"id": "deepseek/deepseek-r1:free",                "label": "DeepSeek R1",          "free": True,  "notes": "free · 65,536 ctx",  "ctx": 65536},
        {"id": "openai/gpt-4o-mini",                       "label": "GPT-4o Mini",          "free": False, "notes": "$0.150/1M · 128,000 ctx", "ctx": 128000},
        {"id": "openai/gpt-4o",                            "label": "GPT-4o",               "free": False, "notes": "$2.500/1M · 128,000 ctx", "ctx": 128000},
        {"id": "anthropic/claude-3.5-sonnet",              "label": "Claude 3.5 Sonnet",    "free": False, "notes": "$3.000/1M · 200,000 ctx", "ctx": 200000},
        {"id": "anthropic/claude-3.5-haiku",               "label": "Claude 3.5 Haiku",     "free": False, "notes": "$0.800/1M · 200,000 ctx", "ctx": 200000},
        {"id": "google/gemini-flash-1.5",                  "label": "Gemini 1.5 Flash",     "free": False, "notes": "$0.075/1M · 1,000,000 ctx", "ctx": 1000000},
    ]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_openrouter_models() -> list[dict]:
    api_key = _get_api_key()
    if not api_key:
        return _FALLBACK_MODELS()
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer":  "https://pear-edtech.app",
                "X-Title":       "Pear EdTech Chatbot",
            },
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json().get("data", [])

        models = []
        for m in raw:
            mid     = m.get("id", "")
            name    = m.get("name", mid)
            ctx     = m.get("context_length", 0)
            pricing = m.get("pricing", {})
            try:
                p_cost  = float(pricing.get("prompt",     1))
                c_cost  = float(pricing.get("completion", 1))
                is_free = p_cost == 0.0 and c_cost == 0.0
            except (ValueError, TypeError):
                is_free = str(pricing.get("prompt", "1")) == "0"

            if is_free:
                cost_str = "free"
            else:
                try:
                    cost_str = f"${float(pricing.get('prompt', 0)) * 1_000_000:.3f}/1M"
                except Exception:
                    cost_str = "paid"

            ctx_str = f"{ctx:,} ctx" if ctx else ""
            notes   = " · ".join(filter(None, [cost_str, ctx_str]))
            models.append({"id": mid, "label": name, "free": is_free, "notes": notes, "ctx": ctx})

        models.sort(key=lambda x: (not x["free"], x["label"].lower()))
        return models if models else _FALLBACK_MODELS()

    except Exception:
        return _FALLBACK_MODELS()


# ══════════════════════════════════════════════════════════════════════════════
# CONVERSATION PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════

def _session_path(session_id: str) -> Path:
    return CHAT_HISTORY_DIR / f"{session_id}.json"


def save_conversation(session_id: str, messages: list[dict], metadata: dict) -> None:
    data = {
        "session_id":  session_id,
        "metadata":    metadata,
        "updated_at":  datetime.now().isoformat(),
        "messages":    messages,
    }
    _session_path(session_id).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_conversation(session_id: str) -> dict | None:
    p = _session_path(session_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_conversations() -> list[dict]:
    """Return saved sessions sorted newest-first."""
    sessions = []
    for fp in sorted(CHAT_HISTORY_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            sessions.append({
                "session_id":  data.get("session_id", fp.stem),
                "title":       data.get("metadata", {}).get("title", fp.stem),
                "model":       data.get("metadata", {}).get("model", ""),
                "updated_at":  data.get("updated_at", ""),
                "msg_count":   len(data.get("messages", [])),
            })
        except Exception:
            continue
    return sessions


def delete_conversation(session_id: str) -> None:
    p = _session_path(session_id)
    if p.exists():
        p.unlink()


def new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def derive_title(messages: list[dict]) -> str:
    """Use the first user message as the conversation title."""
    for m in messages:
        if m.get("role") == "user":
            text = m["content"].strip().replace("\n", " ")
            return text[:60] + "…" if len(text) > 60 else text
    return "Untitled conversation"


# ══════════════════════════════════════════════════════════════════════════════
# KNOWLEDGE BASE LOADING
# ══════════════════════════════════════════════════════════════════════════════

def load_json_file(filepath: Path) -> dict | list | None:
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_html_file(filepath: Path) -> str:
    try:
        soup = BeautifulSoup(filepath.read_text(encoding="utf-8"), "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)
    except Exception:
        return ""


def flatten_json(obj, prefix="") -> str:
    lines = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            lines.append(flatten_json(v, f"{prefix}{k} > " if prefix else f"{k} > "))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            lines.append(flatten_json(v, f"{prefix}[{i}] "))
    else:
        lines.append(f"{prefix.rstrip(' > ')}: {obj}")
    return "\n".join(lines)


def extract_text_from_file(filepath: Path) -> str:
    ext = filepath.suffix.lower()
    if ext == ".json":
        data = load_json_file(filepath)
        return flatten_json(data) if data is not None else ""
    elif ext in (".html", ".htm"):
        return load_html_file(filepath)
    elif ext == ".txt":
        try:
            return filepath.read_text(encoding="utf-8")
        except Exception:
            return ""
    return ""


@st.cache_data(show_spinner="Loading knowledge base…")
def load_all_documents() -> list[dict]:
    docs, seen = [], set()

    # Prioritize the most useful JSON files in your data folder
    PRIORITY_FILES = [
        "news_dataset.json",
        "news_dataset_new.json",
        "news_dataset_new_v2.json",
        "esg_companies.json",
        "esg_keywords.json",
        "esg_keywords_flat.json",
        "news_merged.json",
        "news_content.json",
        "news_extracted.json",
        "extra_text.json"
    ]

    # Load priority files first (with smart chunking for large files)
    for fname in PRIORITY_FILES:
        fp = DATA_DIR / fname
        if not fp.exists() or fp in seen:
            continue
        seen.add(fp)
        try:
            raw = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue

        # If it's a list (e.g. news_dataset.json), chunk into smaller docs
        if isinstance(raw, list) and len(raw) > 0:
            CHUNK_SIZE = 50
            for i in range(0, len(raw), CHUNK_SIZE):
                chunk = raw[i : i + CHUNK_SIZE]
                text  = flatten_json(chunk).strip()
                if not text:
                    continue
                docs.append({
                    "label":    f"{fname} [chunk {i//CHUNK_SIZE + 1}]",
                    "path":     str(fp),
                    "text":     text,
                    "category": fname.replace(".json", ""),
                })
        else:
            text = flatten_json(raw).strip()
            if text:
                docs.append({
                    "label":    fname,
                    "path":     str(fp),
                    "text":     text,
                    "category": fname.replace(".json", ""),
                })

    # Load remaining files (html, txt, other json)
    for pattern in ["**/*.json", "**/*.html", "**/*.htm", "**/*.txt"]:
        for fp in sorted(DATA_DIR.glob(pattern)):
            if CHAT_HISTORY_DIR in fp.parents:
                continue
            if fp in seen:
                continue
            seen.add(fp)
            text = extract_text_from_file(fp).strip()
            if not text:
                continue
            rel_parts = fp.relative_to(DATA_DIR).parts
            category  = rel_parts[0] if len(rel_parts) > 1 else "general"
            docs.append({
                "label":    friendly_label(fp),
                "path":     str(fp),
                "text":     text,
                "category": category,
            })

    return docs


def friendly_label(filepath: Path) -> str:
    try:
        return str(filepath.relative_to(DATA_DIR))
    except ValueError:
        return filepath.name


# ══════════════════════════════════════════════════════════════════════════════
# RETRIEVAL
# ══════════════════════════════════════════════════════════════════════════════

def simple_keyword_score(query: str, text: str) -> float:
    tokens = re.findall(r"\w+", query.lower())
    if not tokens:
        return 0.0
    text_lower = text.lower()
    return sum(text_lower.count(t) for t in tokens) / len(tokens)


def retrieve_top_docs(query: str, docs: list[dict], top_k: int = 5) -> list[dict]:
    scored = [(simple_keyword_score(query, d["text"]), d) for d in docs]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for score, d in scored[:top_k] if score > 0]


def build_context(retrieved: list[dict]) -> str:
    parts, budget = [], MAX_CONTEXT_CHARS
    for d in retrieved:
        snippet = d["text"][:budget]
        parts.append(f"--- Reference: {d['label']} ---\n{snippet}")
        budget -= len(snippet)
        if budget <= 0:
            break
    return "\n\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# OPENROUTER CALL
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT_TEMPLATE = """\
You are Pear, a helpful education advisor assistant.
You answer questions about universities, scholarships, programs, and study abroad opportunities.

You have access to a knowledge base. Relevant excerpts are provided below.

INSTRUCTIONS:
1. Base your answer primarily on the provided references.
2. You MUST cite EVERY reference block you use. Use this exact inline format: [REF: <label>]
   where <label> is copied EXACTLY from the "Reference: <label>" header of that block.
   Example: [REF: output/page_1_uow.json]
3. Place the citation immediately after the sentence that uses the information.
4. If the references do not contain enough information, say so honestly.
5. Be concise, friendly, and structured (use bullet points where helpful).

KNOWLEDGE BASE:
{context}
"""


def call_openrouter(
    messages: list[dict],
    model: str,
    api_key: str,
    temperature: float = 0.3,
) -> tuple[str, list[str]]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://pear-edtech.app",
        "X-Title":       "Pear EdTech Chatbot",
    }
    payload = {"model": model, "messages": messages, "temperature": temperature}
    resp = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    reply = resp.json()["choices"][0]["message"]["content"]
    cited = re.findall(r"\[REF:\s*(.+?)\]", reply)
    return reply, cited


# ══════════════════════════════════════════════════════════════════════════════
# RENDERING
# ══════════════════════════════════════════════════════════════════════════════

def render_message_with_citations(content: str, docs_index: dict):
    parts = re.split(r"(\[REF:\s*.+?\])", content)
    for part in parts:
        m = re.match(r"\[REF:\s*(.+?)\]", part)
        if m:
            label = m.group(1).strip()
            doc   = docs_index.get(label)
            with st.expander(f"📄 {label}", expanded=False):
                if doc:
                    st.caption(f"**Category:** {doc['category']}")
                    st.code(doc["text"][:CHUNK_PREVIEW_LEN] + "…", language=None)
                else:
                    st.write("_Reference not found in loaded documents._")
        else:
            if part.strip():
                st.markdown(part)


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE INIT
# ══════════════════════════════════════════════════════════════════════════════

_DEFAULTS = {
    "api_key":          "",
    "messages":         [],
    "session_id":       new_session_id(),
    "active_model_id":  "meta-llama/llama-3.1-8b-instruct:free",
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    st.title("🤖 Pear AI Chatbot")
    st.caption("Ask anything about universities, scholarships, and study abroad — powered by OpenRouter LLM with local knowledge base.")

    # ── Load models ────────────────────────────────────────────────────────────
    with st.spinner("🔄 Loading models from OpenRouter…"):
        all_models = fetch_openrouter_models()

    free_models = [m for m in all_models if     m["free"]]
    paid_models = [m for m in all_models if not m["free"]]
    id_to_model = {m["id"]: m for m in all_models}

    # ── Sidebar ────────────────────────────────────────────────────────────────
    with st.sidebar:

        # ── API Key ────────────────────────────────────────────────────────────
        st.header("🔑 API Key")
        api_key_input = st.text_input(
            "OpenRouter API Key",
            type="password",
            value=st.session_state.get("api_key", ""),
            help="Get your key at https://openrouter.ai/keys",
        )
        if api_key_input:
            st.session_state["api_key"] = api_key_input

        effective_key = _get_api_key()
        if effective_key:
            st.success("✅ API key set")
        else:
            st.error("❌ API key missing")

        if st.button("🔄 Refresh Model List", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.caption(
            f"**{len(all_models)}** models · "
            f"{len(free_models)} 🆓 free · {len(paid_models)} 💳 paid"
        )

        st.divider()

        # ── Model selector ─────────────────────────────────────────────────────
        st.header("🤖 Model")

        tier = st.radio("Show:", ["🆓 Free Only", "💳 Paid Only", "🔀 All"], horizontal=True)
        visible = (
            free_models if tier == "🆓 Free Only" else
            paid_models if tier == "💳 Paid Only" else
            all_models
        )

        search = st.text_input("🔍 Search", placeholder="llama, claude, mistral…")
        if search.strip():
            visible = [m for m in visible if search.lower() in m["label"].lower() or search.lower() in m["id"].lower()]

        visible_labels = [m["label"] for m in visible]

        # Default to current active model's label if it's in the list
        current_label = id_to_model.get(st.session_state.active_model_id, {}).get("label", "")
        default_idx   = visible_labels.index(current_label) if current_label in visible_labels else 0

        selected_label = st.selectbox(
            f"Select model ({len(visible)} shown)",
            options=visible_labels,
            index=default_idx,
            key="model_selectbox",
        )

        # Resolve selected model
        selected_model = next((m for m in all_models if m["label"] == selected_label), None)
        if selected_model:
            st.session_state.active_model_id = selected_model["id"]
            tier_badge = "🆓 Free" if selected_model["free"] else "💳 Paid"
            st.caption(
                f"{tier_badge} · {selected_model['notes']}\n\n"
                f"`{selected_model['id']}`"
            )

        temperature = st.slider("Temperature", 0.0, 1.0, 0.3, 0.05)
        top_k       = st.slider("Top K references", 1, 10, 5)

        st.divider()

        # ── Knowledge base ─────────────────────────────────────────────────────
        st.header("📂 Knowledge Base")
        docs          = load_all_documents()
        all_cats      = sorted({d["category"] for d in docs})
        selected_cats = st.multiselect("Filter categories", all_cats, default=all_cats)
        filtered_docs = [d for d in docs if d["category"] in selected_cats]
        st.metric("Documents loaded", len(filtered_docs))

        with st.expander("Browse documents"):
            for d in filtered_docs[:50]:
                st.text(f"• {d['label']}")
            if len(filtered_docs) > 50:
                st.caption(f"…and {len(filtered_docs) - 50} more")

        st.divider()

        # ── Conversation history ───────────────────────────────────────────────
        st.header("💬 Conversations")

        if st.button("➕ New Conversation", use_container_width=True):
            # Save current before clearing
            if st.session_state.messages:
                save_conversation(
                    st.session_state.session_id,
                    st.session_state.messages,
                    {
                        "title": derive_title(st.session_state.messages),
                        "model": st.session_state.active_model_id,
                    },
                )
            st.session_state.messages   = []
            st.session_state.session_id = new_session_id()
            st.rerun()

        saved = list_conversations()
        if saved:
            with st.expander(f"📁 Saved ({len(saved)})", expanded=True):
                for s in saved:
                    col_a, col_b = st.columns([5, 1])
                    is_active    = s["session_id"] == st.session_state.session_id
                    label        = f"{'▶ ' if is_active else ''}{s['title']}"
                    col_a.caption(f"**{label}**\n\n_{s['msg_count']} msgs · {s['updated_at'][:16]}_")
                    if col_a.button("Load", key=f"load_{s['session_id']}", use_container_width=True):
                        # Save current first
                        if st.session_state.messages:
                            save_conversation(
                                st.session_state.session_id,
                                st.session_state.messages,
                                {
                                    "title": derive_title(st.session_state.messages),
                                    "model": st.session_state.active_model_id,
                                },
                            )
                        conv = load_conversation(s["session_id"])
                        if conv:
                            st.session_state.messages   = conv["messages"]
                            st.session_state.session_id = s["session_id"]
                            if conv.get("metadata", {}).get("model"):
                                st.session_state.active_model_id = conv["metadata"]["model"]
                        st.rerun()
                    if col_b.button("🗑", key=f"del_{s['session_id']}"):
                        delete_conversation(s["session_id"])
                        if s["session_id"] == st.session_state.session_id:
                            st.session_state.messages   = []
                            st.session_state.session_id = new_session_id()
                        st.rerun()
        else:
            st.caption("No saved conversations yet.")

    # ── Chat area ──────────────────────────────────────────────────────────────
    docs_index = {d["label"]: d for d in filtered_docs}
    
    # Active model info banner
    active_m = id_to_model.get(st.session_state.active_model_id)
    if active_m:
        tier_icon = "🆓" if active_m["free"] else "💳"
        st.caption(f"{tier_icon} **{active_m['label']}** · `{active_m['id']}` · {active_m['notes']}")

    # Render existing messages
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                render_message_with_citations(msg["content"], docs_index)

                cited_refs     = msg.get("references_cited", msg.get("references", []))
                retrieved_refs = msg.get("references_retrieved", [])

                if retrieved_refs:
                    with st.expander(f"🔍 {len(retrieved_refs)} reference(s) used as context", expanded=False):
                        for label in retrieved_refs:
                            doc = docs_index.get(label)
                            cited_badge = "✅ cited" if label in cited_refs else "📄 retrieved"
                            st.markdown(f"**{cited_badge} · {label}**")
                            if doc:
                                st.code(doc["text"][:CHUNK_PREVIEW_LEN] + "…", language=None)

                if cited_refs:
                    st.caption(f"📎 LLM cited: {', '.join(cited_refs)}")

                if msg.get("model_id"):
                    m_info  = id_to_model.get(msg["model_id"])
                    m_label = m_info["label"] if m_info else msg["model_id"]
                    st.caption(f"🤖 `{m_label}` · ⏱ {msg.get('elapsed_s', '?')}s")
            else:
                st.markdown(msg["content"])

    # User input
    if prompt := st.chat_input("Ask about universities, scholarships, programs…"):
        if not effective_key:
            st.error("⚠️ Please enter your OpenRouter API key in the sidebar.")
            st.stop()

        if not filtered_docs:
            st.warning("⚠️ No documents loaded.")
            st.stop()

        # Append + show user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Retrieve & build context
        retrieved = retrieve_top_docs(prompt, filtered_docs, top_k=top_k)
        context   = build_context(retrieved)

        # Build API message list
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context)
        api_messages  = [{"role": "system", "content": system_prompt}]
        for m in st.session_state.messages[-10:]:  # last 10 turns of history
            api_messages.append({"role": m["role"], "content": m["content"]})

        # Call LLM
        with st.chat_message("assistant"):
            with st.spinner(f"Thinking with {active_m['label'] if active_m else 'model'}…"):
                t0 = time.time()
                try:
                    reply, cited = call_openrouter(
                        api_messages,
                        model=st.session_state.active_model_id,
                        api_key=effective_key,
                        temperature=temperature,
                    )
                    elapsed = round(time.time() - t0, 1)
                except requests.HTTPError as e:
                    st.error(f"API error: {e}")
                    st.stop()
                except Exception as e:
                    st.error(f"Unexpected error: {e}")
                    st.stop()

            render_message_with_citations(reply, docs_index)

            # ── Retrieved references — always shown regardless of LLM citations ──
            retrieved_labels = [d["label"] for d in retrieved]
            with st.expander(f"🔍 Retrieved {len(retrieved)} reference(s) from knowledge base", expanded=False):
                for d in retrieved:
                    cited_badge = "✅ cited" if d["label"] in cited else "📄 retrieved"
                    st.markdown(f"**{cited_badge} · {d['label']}** _(category: {d['category']})_")
                    st.code(d["text"][:CHUNK_PREVIEW_LEN] + "…", language=None)

            if cited:
                st.caption(f"📎 LLM cited: {', '.join(cited)}")
            else:
                st.caption("⚠️ LLM did not emit explicit citations — see retrieved references above.")

            if active_m:
                st.caption(f"🤖 `{active_m['label']}` · ⏱ {elapsed}s")

        # Save assistant message — store BOTH retrieved and cited references
        assistant_msg = {
            "role":                "assistant",
            "content":             reply,
            "references_cited":    cited,           # what LLM tagged inline
            "references_retrieved": retrieved_labels, # what was fed as context
            "model_id":            st.session_state.active_model_id,
            "elapsed_s":           elapsed,
            "timestamp":           datetime.now().isoformat(),
        }
        # Keep "references" for backward compat — union of both
        assistant_msg["references"] = list(dict.fromkeys(cited + retrieved_labels))
        st.session_state.messages.append(assistant_msg)

        # ✅ Auto-save conversation to disk after every reply
        save_conversation(
            st.session_state.session_id,
            st.session_state.messages,
            {
                "title": derive_title(st.session_state.messages),
                "model": st.session_state.active_model_id,
            },
        )


# ── Diagram generation via LLM ────────────────────────────────────────────────

MERMAID_PROMPT_TEMPLATE = """\
You are to produce a single Mermaid diagram that represents the key structure / flow described in the input text.
Output MUST be only the Mermaid diagram enclosed in triple backticks with the language tag (```mermaid ... ```).
Do NOT output any extra explanation outside the fenced code block. Use a flowchart (graph TD) or a sequence/diagram that best represents the content.
If the input is a list of report sections, create nodes for each section and arrows to represent flow/relationships.
"""

def extract_mermaid_from_reply(reply: str) -> str:
    """Extract mermaid fenced code block. If none, return entire reply."""
    m = re.search(r"```mermaid\s*(.*?)```", reply, re.S | re.I)
    if not m:
        m = re.search(r"```(?:mermaid)?\s*(.*?)```", reply, re.S | re.I)
    return m.group(1).strip() if m else reply.strip()


def generate_mermaid_from_text(text: str, model: str, api_key: str, temperature: float = 0.2) -> tuple[str, str]:
    """Ask LLM to produce a Mermaid diagram for given text. Returns (mermaid_text, raw_reply)."""
    system = MERMAID_PROMPT_TEMPLATE
    user_msg = f"Input text:\n\n{text}\n\nProduce the diagram now."
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user_msg},
    ]
    raw, _ = call_openrouter(messages=messages, model=model, api_key=api_key, temperature=temperature)
    mermaid = extract_mermaid_from_reply(raw)
    return mermaid, raw


def render_mermaid(mermaid_code: str, height: int = 480):
    """Render Mermaid diagram using client-side Mermaid JS."""
    mermaid_html = f"""
    <div class="mermaid">
    {mermaid_code}
    </div>
    <script>
      (function() {{
        const scriptId = 'mermaid-cdn';
        if (!document.getElementById(scriptId)) {{
          const s = document.createElement('script');
          s.id = scriptId;
          s.type = 'text/javascript';
          s.src = 'https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js';
          document.head.appendChild(s);
          s.onload = function() {{
            mermaid.initialize({{ startOnLoad: true }});
            try {{ mermaid.init(undefined, document.querySelectorAll('.mermaid')); }} catch(e) {{ console.error(e); }}
          }};
        }} else {{
          try {{ mermaid.init(undefined, document.querySelectorAll('.mermaid')); }} catch(e) {{ console.error(e); }}
        }}
      }})();
    </script>
    """
    components.html(mermaid_html, height=height, scrolling=True)


    # ── Chat area ──────────────────────────────────────────────────────────────
    docs_index = {d["label"]: d for d in filtered_docs}
    
    # Active model info banner
    active_m = id_to_model.get(st.session_state.active_model_id)
    if active_m:
        tier_icon = "🆓" if active_m["free"] else "💳"
        st.caption(f"{tier_icon} **{active_m['label']}** · `{active_m['id']}` · {active_m['notes']}")

    # Render existing messages
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                render_message_with_citations(msg["content"], docs_index)

                cited_refs     = msg.get("references_cited", msg.get("references", []))
                retrieved_refs = msg.get("references_retrieved", [])

                if retrieved_refs:
                    with st.expander(f"🔍 {len(retrieved_refs)} reference(s) used as context", expanded=False):
                        for label in retrieved_refs:
                            doc = docs_index.get(label)
                            cited_badge = "✅ cited" if label in cited_refs else "📄 retrieved"
                            st.markdown(f"**{cited_badge} · {label}**")
                            if doc:
                                st.code(doc["text"][:CHUNK_PREVIEW_LEN] + "…", language=None)

                if cited_refs:
                    st.caption(f"📎 LLM cited: {', '.join(cited_refs)}")

                if msg.get("model_id"):
                    m_info  = id_to_model.get(msg["model_id"])
                    m_label = m_info["label"] if m_info else msg["model_id"]
                    st.caption(f"🤖 `{m_label}` · ⏱ {msg.get('elapsed_s', '?')}s")
            else:
                st.markdown(msg["content"])

    # User input
    if prompt := st.chat_input("Ask about universities, scholarships, programs…"):
        if not effective_key:
            st.error("⚠️ Please enter your OpenRouter API key in the sidebar.")
            st.stop()

        if not filtered_docs:
            st.warning("⚠️ No documents loaded.")
            st.stop()

        # Append + show user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Retrieve & build context
        retrieved = retrieve_top_docs(prompt, filtered_docs, top_k=top_k)
        context   = build_context(retrieved)

        # Build API message list
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context)
        api_messages  = [{"role": "system", "content": system_prompt}]
        for m in st.session_state.messages[-10:]:  # last 10 turns of history
            api_messages.append({"role": m["role"], "content": m["content"]})

        # Call LLM
        with st.chat_message("assistant"):
            with st.spinner(f"Thinking with {active_m['label'] if active_m else 'model'}…"):
                t0 = time.time()
                try:
                    reply, cited = call_openrouter(
                        api_messages,
                        model=st.session_state.active_model_id,
                        api_key=effective_key,
                        temperature=temperature,
                    )
                    elapsed = round(time.time() - t0, 1)
                except requests.HTTPError as e:
                    st.error(f"API error: {e}")
                    st.stop()
                except Exception as e:
                    st.error(f"Unexpected error: {e}")
                    st.stop()

            render_message_with_citations(reply, docs_index)

            # ── Retrieved references — always shown regardless of LLM citations ──
            retrieved_labels = [d["label"] for d in retrieved]
            with st.expander(f"🔍 Retrieved {len(retrieved)} reference(s) from knowledge base", expanded=False):
                for d in retrieved:
                    cited_badge = "✅ cited" if d["label"] in cited else "📄 retrieved"
                    st.markdown(f"**{cited_badge} · {d['label']}** _(category: {d['category']})_")
                    st.code(d["text"][:CHUNK_PREVIEW_LEN] + "…", language=None)

            if cited:
                st.caption(f"📎 LLM cited: {', '.join(cited)}")
            else:
                st.caption("⚠️ LLM did not emit explicit citations — see retrieved references above.")

            if active_m:
                st.caption(f"🤖 `{active_m['label']}` · ⏱ {elapsed}s")

        # Save assistant message — store BOTH retrieved and cited references
        assistant_msg = {
            "role":                "assistant",
            "content":             reply,
            "references_cited":    cited,           # what LLM tagged inline
            "references_retrieved": retrieved_labels, # what was fed as context
            "model_id":            st.session_state.active_model_id,
            "elapsed_s":           elapsed,
            "timestamp":           datetime.now().isoformat(),
        }
        # Keep "references" for backward compat — union of both
        assistant_msg["references"] = list(dict.fromkeys(cited + retrieved_labels))
        st.session_state.messages.append(assistant_msg)

        # ✅ Auto-save conversation to disk after every reply
        save_conversation(
            st.session_state.session_id,
            st.session_state.messages,
            {
                "title": derive_title(st.session_state.messages),
                "model": st.session_state.active_model_id,
            },
        )

    # ── Diagram generation UI ─────────────────────────────────────────────────
    st.divider()
    st.header("📊 Generate Diagram for Report")
    st.caption("Use the LLM to convert report text or a selected document into a Mermaid diagram.")

    src_option = st.radio("Source", ["Last assistant reply", "Select document", "Custom text"], horizontal=True)

    source_text = ""
    if src_option == "Last assistant reply":
        # get last assistant message if any
        last_assistant = None
        for m in reversed(st.session_state.messages):
            if m.get("role") == "assistant":
                last_assistant = m
                break
        if last_assistant:
            st.markdown("**Preview (last assistant reply):**")
            st.code(last_assistant["content"][:CHUNK_PREVIEW_LEN] + ("…" if len(last_assistant["content"]) > CHUNK_PREVIEW_LEN else ""))
            source_text = last_assistant["content"]
        else:
            st.info("No assistant reply found in session.")
    elif src_option == "Select document":
        doc_labels = [d["label"] for d in filtered_docs]
        if not doc_labels:
            st.warning("No documents available to select.")
        else:
            sel = st.selectbox("Choose document", options=doc_labels)
            doc = next((d for d in filtered_docs if d["label"] == sel), None)
            if doc:
                st.markdown(f"**Preview ({doc['label']}):**")
                st.code(doc["text"][:CHUNK_PREVIEW_LEN] + ("…" if len(doc["text"]) > CHUNK_PREVIEW_LEN else ""))
                source_text = doc["text"]
    else:
        source_text = st.text_area("Custom text for diagram", height=160)

    col1, col2 = st.columns([1, 1])
    if col1.button("Generate diagram"):
        effective_key = _get_api_key()
        if not effective_key:
            st.error("⚠️ Please enter your OpenRouter API key in the sidebar.")
        elif not source_text or not source_text.strip():
            st.error("⚠️ Provide source text (select a document, have a last assistant reply, or enter custom text).")
        else:
            with st.spinner("Asking LLM to produce Mermaid diagram…"):
                try:
                    mermaid, raw = generate_mermaid_from_text(
                        text=source_text,
                        model=st.session_state.active_model_id,
                        api_key=effective_key,
                        temperature=0.15,
                    )
                except Exception as e:
                    st.error(f"Diagram generation failed: {e}")
                    mermaid = ""
                    raw = ""

            if mermaid:
                st.success("Mermaid diagram produced by LLM:")
                render_mermaid(mermaid, height=520)
                st.download_button("Download .mmd", mermaid, file_name="diagram.mmd", mime="text/plain")
                with st.expander("Raw LLM reply"):
                    st.code(raw)
            else:
                st.warning("LLM did not return Mermaid code. See raw reply below.")
                with st.expander("Raw LLM reply"):
                    st.code(raw)

    if col2.button("Generate and append as assistant message"):
        # Same as generate, but also append as assistant message for conversation history
        effective_key = _get_api_key()
        if not effective_key:
            st.error("⚠️ Please enter your OpenRouter API key in the sidebar.")
        elif not source_text or not source_text.strip():
            st.error("⚠️ Provide source text.")
        else:
            with st.spinner("Generating diagram and saving to conversation…"):
                try:
                    mermaid, raw = generate_mermaid_from_text(
                        text=source_text,
                        model=st.session_state.active_model_id,
                        api_key=effective_key,
                        temperature=0.15,
                    )
                except Exception as e:
                    st.error(f"Diagram generation failed: {e}")
                    mermaid = ""
                    raw = ""

            if mermaid:
                # store as assistant message
                assistant_msg = {
                    "role":                "assistant",
                    "content":             f"(Diagram in Mermaid)\n\n```mermaid\n{mermaid}\n```",
                    "references_cited":    [],
                    "references_retrieved": [],
                    "model_id":            st.session_state.active_model_id,
                    "elapsed_s":           0.0,
                    "timestamp":           datetime.now().isoformat(),
                }
                assistant_msg["references"] = []
                st.session_state.messages.append(assistant_msg)
                save_conversation(
                    st.session_state.session_id,
                    st.session_state.messages,
                    {"title": derive_title(st.session_state.messages), "model": st.session_state.active_model_id},
                )
                st.success("Diagram appended to conversation and saved.")
                render_mermaid(mermaid, height=520)
                st.download_button("Download .mmd", mermaid, file_name="diagram.mmd", mime="text/plain")
            else:
                st.warning("No Mermaid produced. See raw LLM reply:")
                with st.expander("Raw reply"):
                    st.code(raw)


if __name__ == "__main__":
    main()
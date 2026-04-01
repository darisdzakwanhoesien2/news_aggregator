import streamlit as st
import json
import os
import re
import requests
from pathlib import Path
from datetime import datetime
import pandas as pd

st.set_page_config(page_title="LaTeX Report Generator", layout="wide")
st.title("📄 ESG LaTeX Report Generator")

# =============================================
# Paths
# =============================================
DATA_DIR        = Path(__file__).parent.parent.parent / "data"
PROMPTS_DIR     = Path(__file__).parent.parent / "prompts"
REPORTS_DIR     = Path(__file__).parent.parent / "reports"
PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Add output prompt directory for per-section files
OUTPUT_PROMPT_DIR = Path(__file__).parent.parent / "output" / "prompt"
OUTPUT_PROMPT_DIR.mkdir(parents=True, exist_ok=True)

EXTRA_TEXT_FILE = DATA_DIR / "news_content.json" #   "extra_text.json"
NEWS_FILE       = DATA_DIR / "news_dataset_new.json" # "news_content.json" # "news_dataset_new.json"
COMPANIES_FILE  = DATA_DIR / "esg_companies.json"

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

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

# =============================================
# Load Data
# =============================================
@st.cache_data
def load_cleaned_content():
    if EXTRA_TEXT_FILE.exists():
        return json.loads(EXTRA_TEXT_FILE.read_text(encoding="utf-8"))
    return {}

@st.cache_data
def load_news():
    if NEWS_FILE.exists():
        return json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    return []

@st.cache_data
def load_companies():
    if COMPANIES_FILE.exists():
        return json.loads(COMPANIES_FILE.read_text(encoding="utf-8"))
    return []

cleaned_content = load_cleaned_content()
news_data       = load_news()
companies       = load_companies()

# =============================================
# Prompts Store
# =============================================
def load_prompt_template(name: str) -> str:
    fp = PROMPTS_DIR / f"{name}.txt"
    return fp.read_text(encoding="utf-8") if fp.exists() else ""

def save_prompt_template(name: str, content: str):
    fp = PROMPTS_DIR / f"{name}.txt"
    fp.write_text(content, encoding="utf-8")

def list_prompt_templates() -> list:
    return sorted([f.stem for f in PROMPTS_DIR.glob("*.txt")])

# =============================================
# Report State Store
# =============================================
REPORT_STATE_FILE = REPORTS_DIR / "report_state.json"

def load_report_state() -> dict:
    if REPORT_STATE_FILE.exists():
        return json.loads(REPORT_STATE_FILE.read_text(encoding="utf-8"))
    return {"structure": None, "sections": {}, "citations": {}, "metadata": {}}

def save_report_state(state: dict):
    REPORT_STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

# Next output index helper (returns 1,2,3...)
def _next_output_index() -> int:
    """Return next numeric index for OUTPUT_PROMPT_DIR (1,2,3...)."""
    nums = []
    for p in OUTPUT_PROMPT_DIR.glob("*.tex"):
        stem = p.stem
        m = re.match(r"^0*([0-9]+)$", stem)
        if m:
            try:
                nums.append(int(m.group(1)))
            except Exception:
                pass
    return (max(nums) + 1) if nums else 1

def reset_report_state(archive_existing: bool = True):
    """Archive current report_state.json (if any) and clear per-section outputs. Returns fresh state."""
    try:
        if REPORT_STATE_FILE.exists() and archive_existing:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_fp = REPORTS_DIR / f"report_state_{ts}.json"
            REPORT_STATE_FILE.replace(archive_fp)
        elif REPORT_STATE_FILE.exists():
            REPORT_STATE_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    # clear per-section output files
    for p in OUTPUT_PROMPT_DIR.glob("*"):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass

    new_state = {"structure": None, "sections": {}, "citations": {}, "metadata": {}}
    save_report_state(new_state)
    return new_state

# =============================================
# Build Context from Data
# =============================================
def build_context(company_filter: str = "All", max_chars: int = 8000) -> tuple:
    """
    Returns (context_text, citations_list)
    Citations are real article references from cleaned content.
    """
    context_lines = []
    citations = []
    total_chars = 0

    for i, (link, data) in enumerate(cleaned_content.items()):
        if company_filter != "All" and data.get("company_name") != company_filter:
            continue

        title       = data.get("title", "")
        company     = data.get("company_name", "")
        keyword     = data.get("keyword", "")
        published   = data.get("published", "")
        source      = data.get("source", "")
        resolved    = data.get("resolved_url", link)
        content     = data.get("cleaned_content", "")[:1500]  # cap per article

        if not content:
            continue

        entry = (
            f"[REF{i+1}] {title}\n"
            f"Company: {company} | Topic: {keyword} | Date: {published} | Source: {source}\n"
            f"{content}\n"
        )

        if total_chars + len(entry) > max_chars:
            break

        context_lines.append(entry)
        total_chars += len(entry)

        citations.append({
            "ref_id": f"REF{i+1}",
            "title": title,
            "company": company,
            "source": source,
            "published": published,
            "url": resolved,
        })

    return "\n\n".join(context_lines), citations

# =============================================
# LLM Call
# =============================================
def call_llm(system_prompt: str, user_prompt: str, api_key: str, model: str) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens":  4096,
    }
    try:
        resp = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[LLM Error: {str(e)}]"

# =============================================
# LaTeX Helpers
# =============================================
def build_bibliography(citations: list) -> str:
    """Generate BibTeX entries from real article citations."""
    bib_lines = ["\\begin{thebibliography}{99}"]
    for c in citations:
        ref_id  = c["ref_id"].replace(" ", "")
        title   = c["title"].replace("&", "\\&").replace("%", "\\%")
        source  = c["source"].replace("&", "\\&")
        pub     = c["published"][:10] if c["published"] else ""
        url     = c["url"]
        bib_lines.append(
            f"\\bibitem{{{ref_id}}}\n"
            f"{c['company']}. ``{title}''\n"
            f"\\textit{{{source}}}, {pub}.\n"
            f"\\url{{{url}}}\n"
        )
    bib_lines.append("\\end{thebibliography}")
    return "\n".join(bib_lines)

def wrap_latex_document(title: str, author: str, sections_latex: str, bibliography: str) -> str:
    return f"""\\documentclass[12pt,a4paper]{{report}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[T1]{{fontenc}}
\\usepackage{{geometry}}
\\usepackage{{hyperref}}
\\usepackage{{url}}
\\usepackage{{booktabs}}
\\usepackage{{graphicx}}
\\usepackage{{amsmath}}
\\usepackage{{setspace}}
\\geometry{{margin=2.5cm}}
\\onehalfspacing

\\title{{{title}}}
\\author{{{author}}}
\\date{{\\today}}

\\begin{{document}}
\\maketitle
\\tableofcontents
\\newpage

{sections_latex}

{bibliography}

\\end{{document}}
"""

# =============================================
# Default Prompt Templates
# =============================================
DEFAULT_PROMPTS = {
    "00_structure": """You are an expert ESG analyst. Based on the provided news context about Indonesian companies, 
generate a detailed LaTeX report structure (table of contents only) for a ~40 page ESG analysis report.

Return ONLY a JSON array of sections like:
[
  {{"section_id": "1", "title": "Executive Summary", "description": "Brief overview of findings", "latex_cmd": "chapter"}},
  {{"section_id": "1.1", "title": "Key Findings", "description": "...", "latex_cmd": "section"}},
  ...
]

Context:
{context}""",

    "01_executive_summary": """You are an expert ESG analyst writing a formal LaTeX report.
Write ONLY the LaTeX content (no \\documentclass, no preamble) for the section: **{section_title}**

Requirements:
- Use \\chapter{{ }} or \\section{{ }} as appropriate
- Cite sources using \\cite{{REF_ID}} where relevant
- Be analytical, formal, and data-driven
- Approx 500-800 words
- Include key statistics and findings from the context

Context:
{context}

Section description: {section_description}""",

    "section_generic": """You are an expert ESG analyst writing a formal LaTeX report.
Write ONLY the LaTeX content (no \\documentclass, no preamble) for the section: **{section_title}**

Requirements:
- Use appropriate LaTeX sectioning commands
- Cite sources inline using \\cite{{REF_ID}} based on the provided references
- Be specific to Indonesian ESG context
- Approx 600-1000 words
- Include analysis, not just summaries

Available references in context:
{context}

Section description: {section_description}""",
}

# Initialize default prompts if not exist
for name, content in DEFAULT_PROMPTS.items():
    if not (PROMPTS_DIR / f"{name}.txt").exists():
        save_prompt_template(name, content)

# =============================================
# UI
# =============================================

# Sidebar config
with st.sidebar:
    st.header("⚙️ Configuration")

    # API Key
    api_key_input = st.text_input(
        "OpenRouter API Key",
        type="password",
        value=st.session_state.get("api_key", os.environ.get("OPENROUTER_API_KEY", "")),
        help="Get your key at https://openrouter.ai/keys",
    )
    if api_key_input:
        st.session_state["api_key"] = api_key_input
    api_key = st.session_state.get("api_key", "")

    # Fetch models from OpenRouter
    with st.spinner("🔄 Loading models from OpenRouter…"):
        all_models = fetch_openrouter_models()
    free_models = [m for m in all_models if     m["free"]]
    paid_models = [m for m in all_models if not m["free"]]
    id_to_model = {m["id"]: m for m in all_models}

    if st.button("🔄 Refresh Model List", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.caption(
        f"**{len(all_models)}** models · "
        f"{len(free_models)} 🆓 free · {len(paid_models)} 💳 paid"
    )

    st.divider()

    # Model selector
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
    if "active_model_id" not in st.session_state:
        st.session_state["active_model_id"] = "anthropic/claude-3.5-sonnet"
    current_label = id_to_model.get(st.session_state["active_model_id"], {}).get("label", "")
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
        st.session_state["active_model_id"] = selected_model["id"]
        tier_badge = "🆓 Free" if selected_model["free"] else "💳 Paid"
        st.caption(
            f"{tier_badge} · {selected_model['notes']}\n\n"
            f"`{selected_model['id']}`"
        )
    model = st.session_state["active_model_id"]

    company_filter = st.selectbox(
        "Focus Company",
        ["All"] + sorted(set(d.get("company_name", "") for d in cleaned_content.values() if d.get("company_name")))
    )

    report_title  = st.text_input("Report Title", value="ESG Analysis Report: Indonesian Companies")
    report_author = st.text_input("Author", value="ESG Research Team")

    st.markdown("---")
    st.markdown(f"📂 **Prompts dir:** `new_app/prompts/`")
    st.markdown(f"📂 **Reports dir:** `new_app/reports/`")
    st.markdown(f"📰 **Articles available:** {len(cleaned_content)}")

# Load state
report_state = load_report_state()

# =============================================
# TABS
# =============================================
tab1, tab2, tab3, tab4 = st.tabs([
    "📐 Step 1: Structure",
    "✍️ Step 2: Generate Sections",
    "🔧 Step 3: Prompt Editor",
    "📄 Step 4: Compile & Export"
])

# ─────────────────────────────────────────────
# TAB 1: Generate Structure
# ─────────────────────────────────────────────
with tab1:
    st.subheader("📐 Step 1: Generate Report Structure")
    st.info("First, generate the report structure (Table of Contents). This defines all sections to be written.")

    context_text, citations = build_context(company_filter, max_chars=6000)
    st.caption(f"Context built from **{len(citations)}** articles")

    structure_prompt_template = load_prompt_template("00_structure")
    structure_prompt = st.text_area(
        "Structure Prompt (edit if needed):",
        value=structure_prompt_template,
        height=250
    )

    if st.button("🏗️ Generate Structure", type="primary"):
        if not api_key:
            st.error("❌ Please enter your API key in the sidebar.")
        else:
            with st.spinner("Generating report structure..."):
                filled_prompt = structure_prompt.replace("{context}", context_text[:4000])
                raw_response  = call_llm(
                    system_prompt="You are an expert ESG report writer. Always return valid JSON.",
                    user_prompt=filled_prompt,
                    api_key=api_key,
                    model=model
                )

            # Robust JSON extraction: try json.loads, ast.literal_eval, then a safe single->double-quote pass
            def _extract_json_array(text: str):
                m = re.search(r'\[.*\]', text, re.DOTALL)
                if not m:
                    return None
                s = m.group()

                # Normalize common LLM formatting issues:
                # - double-braces like {{ ... }} -> { ... }
                # - trailing commas before closing } or ] which break json.loads
                s_clean = re.sub(r'\{\{', '{', s)
                s_clean = re.sub(r'\}\}', '}', s_clean)
                s_clean = re.sub(r',\s*([}\]])', r'\1', s_clean)

                # Try a few parsers in order of safety
                for candidate in (s, s_clean):
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, list):
                            return parsed
                    except Exception:
                        pass
                    try:
                        parsed = ast.literal_eval(candidate)
                        if isinstance(parsed, list):
                            return parsed
                    except Exception:
                        pass

                # Last-ditch: naive single-quote -> double-quote convert (may fail on nested quotes)
                try:
                    s2 = re.sub(r"(?<!\\)'", '"', s_clean)
                    parsed = json.loads(s2)
                    if isinstance(parsed, list):
                        return parsed
                except Exception:
                    pass

                return None

            structure = _extract_json_array(raw_response)
            if structure:
                report_state["structure"] = structure
                report_state["metadata"]  = {
                    "title":      report_title,
                    "author":     report_author,
                    "created_at": datetime.now().isoformat(),
                    "company_filter": company_filter,
                }
                save_report_state(report_state)
                save_prompt_template("00_structure", structure_prompt)
                st.success(f"✅ Structure generated with **{len(structure)}** sections!")
            else:
                st.error("Could not parse JSON. Raw response:")
                with st.expander("LLM raw response (debug)", expanded=True):
                    st.code(raw_response)

    # Show current structure
    if report_state.get("structure"):
        st.markdown("#### 📋 Current Structure")
        structure_df = []
        for s in report_state["structure"]:
            generated = s["section_id"] in report_state.get("sections", {})
            structure_df.append({
                "ID":          s["section_id"],   # fixed: closed the string/lookup
                "Title":       s["title"],
                "Command":     s.get("latex_cmd", "section"),
                "Description": s.get("description", "")[:80],
                "Generated":   "✅" if generated else "⏳",
            })
        st.dataframe(structure_df, use_container_width=True)

# ─────────────────────────────────────────────
# TAB 2: Generate Sections
# ─────────────────────────────────────────────
with tab2:
    st.subheader("✍️ Step 2: Generate Sections")

    if not report_state.get("structure"):
        st.warning("⚠️ Please generate the report structure in Step 1 first.")
    else:
        structure = report_state["structure"]
        sections  = report_state.get("sections", {})
        citations_store = report_state.get("citations", {})

        # Section selector
        section_options = {f"{s['section_id']} — {s['title']}": s for s in structure}
        selected_label  = st.selectbox("Select Section to Generate:", list(section_options.keys()))
        selected_section = section_options[selected_label]

        context_text, citations = build_context(company_filter, max_chars=8000)

        # Pick prompt template
        prompt_files    = list_prompt_templates()
        prompt_choices  = [p for p in prompt_files if p not in ["00_structure"]]
        selected_prompt = st.selectbox(
            "Prompt template to use:",
            prompt_choices if prompt_choices else ["section_generic"]
        )

        template_content = load_prompt_template(selected_prompt)
        filled = (template_content
                  .replace("{section_title}", selected_section["title"])
                  .replace("{section_description}", selected_section.get("description", ""))
                  .replace("{context}", context_text))

        editable_prompt = st.text_area("Prompt (editable):", value=filled, height=300)

        col_gen, col_regen = st.columns([2, 1])
        with col_gen:
            generate_btn = st.button("✍️ Generate This Section", type="primary")
        with col_regen:
            if selected_section["section_id"] in sections:
                st.success("✅ Already generated")
            if st.button("🔁 Start New Report (archive + clear)"):
                report_state = reset_report_state(archive_existing=True)
                sections = report_state.get("sections", {})
                citations_store = report_state.get("citations", {})
                st.success("✅ New report started (old state archived, outputs cleared).")
                st.rerun()

        if generate_btn:
            if not api_key:
                st.error("❌ Please enter your API key.")
            else:
                with st.spinner(f"Generating: {selected_section['title']}..."):
                    latex_content = call_llm(
                        system_prompt="You are an expert LaTeX ESG report writer. Return only valid LaTeX content.",
                        user_prompt=editable_prompt,
                        api_key=api_key,
                        model=model
                    )

                # assign next numeric file index
                file_index = _next_output_index()

                sections[selected_section["section_id"]] = {
                    "title":     selected_section["title"],
                    "latex_cmd": selected_section.get("latex_cmd", "section"),
                    "content":   latex_content,
                    "generated_at": datetime.now().isoformat(),
                    "file_index": file_index,
                }
                citations_store[selected_section["section_id"]] = citations

                # write to numeric files
                tex_path = OUTPUT_PROMPT_DIR / f"{file_index}.tex"
                json_path = OUTPUT_PROMPT_DIR / f"{file_index}.json"
                tex_path.write_text(latex_content, encoding="utf-8")
                json_path.write_text(json.dumps(citations, indent=2, ensure_ascii=False), encoding="utf-8")

                report_state["sections"]  = sections
                report_state["citations"] = citations_store
                save_report_state(report_state)
                st.success(f"✅ Section generated and saved as {file_index}.tex")

        # Preview
        if selected_section["section_id"] in sections:
            with st.expander("👁️ Preview LaTeX Output", expanded=True):
                st.code(sections[selected_section["section_id"]]["content"], language="latex")

        # Generate All button
        st.markdown("---")
        st.markdown("#### 🚀 Generate All Remaining Sections")
        remaining = [s for s in structure if s["section_id"] not in sections]
        st.info(f"**{len(remaining)}** sections remaining out of **{len(structure)}** total.")

        if st.button(f"🚀 Auto-Generate All {len(remaining)} Remaining Sections"):
            if not api_key:
                st.error("❌ Please enter your API key.")
            else:
                progress = st.progress(0)
                status   = st.empty()
                context_text, citations = build_context(company_filter, max_chars=8000)
                template = load_prompt_template("section_generic")

                for i, sec in enumerate(remaining):
                    status.text(f"Generating ({i+1}/{len(remaining)}): {sec['title']}...")
                    filled = (template
                              .replace("{section_title}", sec["title"])
                              .replace("{section_description}", sec.get("description", ""))
                              .replace("{context}", context_text))

                    latex_content = call_llm(
                        system_prompt="You are an expert LaTeX ESG report writer. Return only valid LaTeX content.",
                        user_prompt=filled,
                        api_key=api_key,
                        model=model
                    )

                    # Save each section and its citations immediately
                    sections[sec["section_id"]] = {
                        "title":     sec["title"],
                        "latex_cmd": sec.get("latex_cmd", "section"),
                        "content":   latex_content,
                        "generated_at": datetime.now().isoformat(),
                    }
                    citations_store[sec["section_id"]] = citations

                    # Save to output/prompt/{section_id}.tex and .json
                    tex_path = OUTPUT_PROMPT_DIR / f"{sec['section_id']}.tex"
                    json_path = OUTPUT_PROMPT_DIR / f"{sec['section_id']}.json"
                    tex_path.write_text(latex_content, encoding="utf-8")
                    json_path.write_text(json.dumps(citations, indent=2, ensure_ascii=False), encoding="utf-8")

                    report_state["sections"]  = sections
                    report_state["citations"] = citations_store
                    save_report_state(report_state)  # <-- Save after each section

                    progress.progress((i + 1) / len(remaining))

                status.text("✅ All sections generated!")
                st.success("✅ All sections generated and saved!")

# ─────────────────────────────────────────────
# TAB 3: Prompt Editor
# ─────────────────────────────────────────────
with tab3:
    st.subheader("🔧 Step 3: Prompt Template Editor")
    st.info("Edit, create, or delete prompt templates stored in `new_app/prompts/`")

    col_list, col_edit = st.columns([1, 2])

    with col_list:
        st.markdown("**Available Templates:**")
        for name in list_prompt_templates():
            st.markdown(f"- `{name}.txt`")

        st.markdown("---")
        new_prompt_name = st.text_input("New template name:", placeholder="e.g. section_risks")
        if st.button("➕ Create New Template"):
            if new_prompt_name:
                save_prompt_template(new_prompt_name, DEFAULT_PROMPTS.get("section_generic", ""))
                st.success(f"✅ Created `{new_prompt_name}.txt`")
                st.rerun()

    with col_edit:
        all_templates = list_prompt_templates()
        if all_templates:
            edit_target  = st.selectbox("Edit template:", all_templates)
            edit_content = st.text_area(
                "Template content:",
                value=load_prompt_template(edit_target),
                height=400
            )
            col_save, col_del = st.columns(2)
            with col_save:
                if st.button("💾 Save Template"):
                    save_prompt_template(edit_target, edit_content)
                    st.success("✅ Saved!")
            with col_del:
                if st.button("🗑️ Delete Template", type="secondary"):
                    (PROMPTS_DIR / f"{edit_target}.txt").unlink(missing_ok=True)
                    st.warning(f"Deleted `{edit_target}.txt`")
                    st.rerun()

            st.markdown("**Available variables:**")
            st.code("{section_title}  → Section name\n{section_description}  → Section description\n{context}  → Article content + citations", language="text")

# ─────────────────────────────────────────────
# TAB 4: Compile & Export
# ─────────────────────────────────────────────
with tab4:
    st.subheader("📄 Step 4: Compile & Export LaTeX Report")

    sections = report_state.get("sections", {})
    if not sections:
        st.warning("⚠️ No sections generated yet. Complete Steps 1 & 2 first.")
    else:
        structure    = report_state.get("structure", [])
        ordered_ids  = [s["section_id"] for s in structure]
        all_citations = []

        # Assemble sections in order
        sections_latex = ""
        for sec_id in ordered_ids:
            if sec_id in sections:
                sections_latex += sections[sec_id]["content"] + "\n\n"
                all_citations.extend(report_state.get("citations", {}).get(sec_id, []))

        # Deduplicate citations by ref_id
        seen_refs = set()
        unique_citations = []
        for c in all_citations:
            if c["ref_id"] not in seen_refs:
                unique_citations.append(c)
                seen_refs.add(c["ref_id"])

        bibliography = build_bibliography(unique_citations)
        full_latex   = wrap_latex_document(
            title=report_state.get("metadata", {}).get("title", report_title),
            author=report_state.get("metadata", {}).get("author", report_author),
            sections_latex=sections_latex,
            bibliography=bibliography,
        )

        # Summary
        col1, col2, col3 = st.columns(3)
        col1.metric("📝 Sections Generated", len(sections))
        col2.metric("📚 Unique Citations",    len(unique_citations))
        col3.metric("📄 Estimated Characters", f"{len(full_latex):,}")

        # Preview
        with st.expander("👁️ Preview Full LaTeX", expanded=False):
            st.code(full_latex, language="latex")

        # Citations table
        with st.expander(f"📚 View {len(unique_citations)} Citations"):
            if unique_citations:
                st.dataframe(pd.DataFrame(unique_citations), use_container_width=True)

        st.markdown("---")
        st.markdown("#### 📥 Export")

        col_dl1, col_dl2 = st.columns(2)

        # Download .tex file
        with col_dl1:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            tex_filename = f"esg_report_{timestamp}.tex"
            st.download_button(
                label="⬇️ Download .tex File",
                data=full_latex.encode("utf-8"),
                file_name=tex_filename,
                mime="text/plain",
                type="primary"
            )

        # Download citations as JSON
        with col_dl2:
            st.download_button(
                label="⬇️ Download Citations JSON",
                data=json.dumps(unique_citations, indent=2, ensure_ascii=False).encode("utf-8"),
                file_name=f"citations_{timestamp}.json",
                mime="application/json"
            )

        # Save to reports dir
        if st.button("💾 Save to `new_app/reports/`"):
            report_path = REPORTS_DIR / tex_filename
            report_path.write_text(full_latex, encoding="utf-8")
            citations_path = REPORTS_DIR / f"citations_{timestamp}.json"
            citations_path.write_text(json.dumps(unique_citations, indent=2, ensure_ascii=False), encoding="utf-8")
            st.success(f"✅ Saved to `new_app/reports/{tex_filename}`")

        # Compile instructions
        st.markdown("---")
        st.markdown("#### 🖥️ Compile to PDF (Terminal)")
        st.code(f"""cd new_app/reports/
pdflatex {tex_filename}
pdflatex {tex_filename}   # Run twice for TOC
""", language="bash")
        st.caption("Make sure you have `pdflatex` installed: `brew install --cask mactex`")
# ============================================================
# 12_research_structure.py
# ============================================================

import streamlit as st
from pathlib import Path
import os
import glob
import json

# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Research Structure & Templates",
    page_icon="📚",
    layout="wide"
)

# ============================================================
# HELPERS
# ============================================================

def load_markdown(file_path: str) -> str:
    """Load markdown file safely"""
    try:
        path = Path(file_path)
        if path.exists():
            return path.read_text(encoding="utf-8")
        else:
            return f"⚠️ File not found: {file_path}"
    except Exception as e:
        return f"❌ Error loading file: {str(e)}"


def list_markdown_files(dir_path: str, recursive: bool = True):
    """Return sorted list of .md files under dir_path"""
    try:
        base = Path(dir_path)
        if not base.exists():
            return []
        pattern = "**/*.md" if recursive else "*.md"
        files = [str(p) for p in base.glob(pattern)]
        return sorted(files)
    except Exception:
        return []

# Default metadata mapping for templates
DEFAULT_TEMPLATE_METADATA = {
    "header_prompt": "You are an academic researcher writing a Master's thesis.",
    "title": "Thesis Title: \"Neurosymbolic Reasoning for Robust Greenwashing Detection and Actionable ESG Analysis\""
}

def load_metadata(path: str):
    try:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return DEFAULT_TEMPLATE_METADATA.copy()

def save_metadata(path: str, obj: dict):
    Path(path).write_text(json.dumps(obj, indent=2), encoding="utf-8")


def section_header(title, icon="📌"):
    st.markdown(f"## {icon} {title}")
    st.divider()


# ============================================================
# SIDEBAR NAVIGATION
# ============================================================

st.sidebar.title("📚 Navigation")

section = st.sidebar.radio(
    "Go to Section",
    [
        "Overview",
        "Research Pipeline",
        "LLM Workflow",
        "Templates (Markdown)",
        "Schema Design",
        "Validation Layer"
    ]
)

# ============================================================
# MAIN HEADER
# ============================================================

st.title("📚 Research Structure & Documentation")
st.caption("Neurosymbolic + LLM Pipeline for ESG / IELTS Generation")

# ============================================================
# SECTION: OVERVIEW
# ============================================================

if section == "Overview":
    section_header("Research Overview")

    st.markdown("""
### 🎯 Objective
Build a **robust, modular LLM system** for:

- Question Generation (IELTS / ESG)
- Answer Verification
- Difficulty Estimation
- Schema Validation

---

### 🧠 Core Idea
Combine:

- LLM reasoning
- Structured validation
- Pipeline modularization
""")

    st.info("This page acts as a bridge between thesis + implementation.")

# ============================================================
# SECTION: PIPELINE
# ============================================================

elif section == "Research Pipeline":
    section_header("End-to-End Pipeline")

    st.markdown("""

[1] Input Source
↓
[2] Context Extraction
↓
[3] Question Generation (LLM)
↓
[4] Answer Verification (LLM)
↓
[5] Difficulty Estimation
↓
[6] Schema Validation + Normalization
↓
[7] Final Output (JSON)

""")

    st.success("Pipeline is modular — each stage can be independently improved.")

# ============================================================
# SECTION: LLM WORKFLOW
# ============================================================

elif section == "LLM Workflow":
    section_header("LLM Design Strategy")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("Zero-shot")
        st.write("""
- Fast
- No examples
- Less reliable
""")

    with col2:
        st.subheader("Few-shot")
        st.write("""
- Guided generation
- Better structure
- Moderate cost
""")

    with col3:
        st.subheader("Chain-of-Thought")
        st.write("""
- High reasoning
- Transparent
- Best accuracy
""")

    st.warning("Use CoT for verification + difficulty estimation.")

# ============================================================
# SECTION: MARKDOWN TEMPLATE
# ============================================================

elif section == "Templates (Markdown)":
    section_header("Template Documentation")

    base_dir = "new_app/pages/documentation_succesful"
    st.markdown("### 📂 Markdown Templates Directory")
    st.caption(base_dir)

    md_files = list_markdown_files(base_dir)
    if not md_files:
        st.warning("No .md files found in the templates directory.")
    else:
        selected = st.selectbox("Select a markdown file to view", md_files)
        st.code(selected)
        st.markdown("---")
        md_content = load_markdown(selected)
        # show basic file info
        try:
            stat = Path(selected).stat()
            st.caption(f"Last modified: {Path(selected).stat().st_mtime}")
        except Exception:
            pass

        # load template metadata (used for placeholder mapping)
        meta_path = Path(base_dir) / "template_metadata.json"
        metadata = load_metadata(str(meta_path))

        # Replace any metadata literal values in the markdown with their placeholders.
        # This generalizes replacement so "title" (and other keys) are replaced too.
        for key, val in metadata.items():
            if not isinstance(val, str) or not val:
                continue
            placeholder = "{" + key + "}"
            # direct match
            if val in md_content:
                md_content = md_content.replace(val, placeholder)
            # match without surrounding quotes (common in templates)
            val_no_quotes = val.replace('"', '')
            if val_no_quotes in md_content:
                md_content = md_content.replace(val_no_quotes, placeholder)
            # match without a trailing period
            val_no_period = val.rstrip(".")
            if val_no_period in md_content:
                md_content = md_content.replace(val_no_period, placeholder)

        st.markdown(md_content, unsafe_allow_html=True)

        # --- Template metadata editor / viewer ---
        # metadata already loaded above
        st.markdown("---")
        st.markdown("### 🔖 Template Metadata")
        edited = st.text_area("Edit JSON metadata", value=json.dumps(metadata, indent=2), height=200)
        col_save, _ = st.columns([1, 3])
        with col_save:
            if st.button("Save metadata"):
                try:
                    parsed = json.loads(edited)
                    save_metadata(str(meta_path), parsed)
                    st.success("Template metadata saved.")
                except Exception as e:
                    st.error(f"Failed to save metadata: {e}")
        # show parsed JSON preview
        try:
            st.json(json.loads(edited))
        except Exception:
            st.info("Current metadata is not valid JSON.")

# ============================================================
# SECTION: SCHEMA DESIGN
# ============================================================

elif section == "Schema Design":
    section_header("Final JSON Schema")

    st.code("""
{
  "question_id": "string",
  "type": "IELTS",
  "difficulty": "easy | medium | hard",
  "question": "string",
  "options": ["A", "B", "C", "D"],
  "correct_answer": "A",
  "explanation": "string",
  "verification": {
      "status": "correct | incorrect",
      "confidence": 0.0
  }
}
""", language="json")

    st.success("Schema ensures consistency across all generated outputs.")

# ============================================================
# SECTION: VALIDATION
# ============================================================

elif section == "Validation Layer":
    section_header("Validation & Normalization")

    st.markdown("""
### ✅ Validation Steps

1. JSON format check
2. Required fields check
3. Answer consistency
4. Difficulty normalization
5. LLM self-verification

---

### 🔁 Normalization

- Convert labels → standard format
- Ensure consistent difficulty scale
- Clean text artifacts
""")

    st.info("This is where robustness is enforced.")
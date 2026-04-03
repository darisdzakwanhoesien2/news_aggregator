# ============================================================
# 12_research_structure.py
# ============================================================

import streamlit as st
from pathlib import Path

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

    md_path = "new_app/pages/documentation_succesful/001_templates.md"
    md_content = load_markdown(md_path)

    st.markdown("### 📄 Loaded Template File")
    st.code(md_path)

    st.markdown("---")

    st.markdown(md_content, unsafe_allow_html=True)

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
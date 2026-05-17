import streamlit as st


st.set_page_config(page_title="Research Workflow", layout="wide")

st.title("Research Workflow Hub")
st.caption(
    "Navigation page for the OCR, verification, chatbot, and report-generation tools "
    "inside `new_app/`."
)

st.markdown(
    """
Use the sidebar to open the working pages for this app.

- `1_*` pages handle news collection and recovery.
- `0_0_0_2_Bulk_OCR.py` manages document OCR ingestion.
- `7_*`, `10_*`, and `11_*` pages cover ESG MCQ verification variants.
- `5_chatbot_llm.py`, `8_generative_report_image.py`, and `6_Report_Generator.py` support research analysis and reporting.
"""
)

with st.expander("App guide", expanded=False):
    st.markdown(
        """
**Purpose**

This Streamlit app groups the research-oriented workflows in the repository: data collection,
OCR extraction, LLM verification, documentation support, and report generation.

**Recommended order**

- Collect or repair news content with the `1_*` pages.
- OCR supporting documents with `0_0_0_2_Bulk_OCR.py`.
- Run verification or scoring from the `7_*`, `10_*`, or `11_*` pages.
- Summarize results with `verification_dashboard.py` and generate written output with `6_Report_Generator.py`.
"""
    )

from pathlib import Path

import streamlit as st


PAGE_DESCRIPTIONS = {
    "01_login.py": {
        "summary": "Authenticate an existing user, recover sessions, or enter the public-account workflow.",
        "purpose": "Use this page to sign in to the UKM ESG system and route authenticated users to their personalized dashboard and assessment tools.",
        "workflow": [
            "Validate local credentials from the JSON-backed user store.",
            "Restore the active user into Streamlit session state.",
            "Redirect the user into the dashboard or related pages.",
        ],
        "data": ["Inputs: `public_account/user_data/users.json` or `public_account/users.json`"],
        "notes": ["Passwords are stored as salted PBKDF2 hashes."],
    },
    "02_register.py": {
        "summary": "Create a new public-account user profile with role metadata.",
        "purpose": "Use this page to register new UKM, supplier, or bank users and initialize their local account records.",
        "workflow": [
            "Collect profile and credential details.",
            "Hash the password before storage.",
            "Append the new user to the local JSON user store.",
        ],
        "data": ["Outputs: user records in `public_account/user_data/users.json`"],
        "notes": ["This is the entry point for new users of the public portal."],
    },
    "03_dashboard.py": {
        "summary": "Personal dashboard for a logged-in user, including session history and result summaries.",
        "purpose": "Use this page to review the current user profile, browse recent verification sessions, and navigate into the active assessment workflows.",
        "workflow": [
            "Resolve the logged-in user from session state or query params.",
            "Load stored session metadata and verification summaries.",
            "Present personalized cards, metrics, and recent activity.",
        ],
        "data": ["Inputs: `public_account/user_data/` session folders and user metadata"],
        "notes": ["Main landing page after successful authentication."],
    },
    "04_form_assessment.py": {
        "summary": "Full ESG assessment workflow with answer source selection, OCR, and LLM verification.",
        "purpose": "Use this page to run the complete user-facing scoring flow: choose answers, upload evidence documents, run OCR-backed verification, and export results.",
        "workflow": [
            "Select the company and answer source.",
            "Upload documents and extract OCR text.",
            "Run LLM verification and score the submission.",
        ],
        "data": ["Outputs: session folders with inputs, OCR outputs, verification JSON, and score CSV files"],
        "notes": ["Most complete assessment experience in the public portal."],
    },
    "04_form_assessment_afterLogin.py": {
        "summary": "Authenticated variant of the full OCR plus LLM assessment workflow.",
        "purpose": "Use this page when the assessment should be explicitly bound to a signed-in user and stored in that user’s session history.",
        "workflow": [
            "Load the authenticated user context.",
            "Run answer selection, OCR, verification, and scoring.",
            "Write outputs to the user’s session folder for later review.",
        ],
        "data": ["Inputs and outputs: user-scoped session folders under `public_account/user_data/`"],
        "notes": ["Best fit for production-style user journeys."],
    },
    "04_form_assessment_withoutPDF.py": {
        "summary": "Form-only ESG assessment flow without OCR or LLM verification.",
        "purpose": "Use this page when respondents should submit answers directly and receive form-based scoring without document evidence processing.",
        "workflow": [
            "Collect questionnaire answers and company context.",
            "Calculate form-only scores locally.",
            "Save the submission and allow later review.",
        ],
        "data": ["Outputs: saved submission JSON and score summaries"],
        "notes": ["Fastest assessment mode for manual submissions."],
    },
    "04_form_assessment_withoutPDF_generalized.py": {
        "summary": "Generalized form-only MCQ workflow for configurable assessment sets.",
        "purpose": "Use this page when the questionnaire structure needs to be more reusable than the fixed form-only assessment page.",
        "workflow": [
            "Load configurable question or company context.",
            "Capture answers without OCR or LLM steps.",
            "Produce summarized scoring and downloadable outputs.",
        ],
        "data": ["Inputs: generalized MCQ configuration JSON files"],
        "notes": ["Reusable no-document assessment flow."],
    },
    "04_form_assessment_withoutPDF_generalized_weightage.py": {
        "summary": "Weighted generalized form-only assessment workflow.",
        "purpose": "Use this page when form-only scoring should respect configurable question or pillar weights instead of uniform scoring.",
        "workflow": [
            "Load weighted assessment configuration.",
            "Collect user answers.",
            "Calculate weighted pillar and total scores.",
        ],
        "data": ["Inputs: weighted MCQ configuration data"],
        "notes": ["Variant of the generalized form-only scorer with weighting logic."],
    },
    "05_results.py": {
        "summary": "Result viewer for completed verification sessions.",
        "purpose": "Use this page to open stored assessment outputs, inspect score tables, and review raw verification payloads without re-running the workflow.",
        "workflow": [
            "Load the selected session or query-param target.",
            "Display structured score tables.",
            "Expose raw verification details for audit or download.",
        ],
        "data": ["Inputs: saved session outputs under `public_account/user_data/`"],
        "notes": ["Read-only review page for completed runs."],
    },
    "ukm_files.py": {
        "summary": "File manager for a user’s uploaded assessment documents.",
        "purpose": "Use this page to upload new supporting files and review what is already stored for the authenticated account.",
        "workflow": [
            "Resolve the current user context.",
            "Upload one or more files into the user’s storage area.",
            "Browse and manage the saved file list.",
        ],
        "data": ["Outputs: file assets stored inside user-scoped directories under `public_account/user_data/`"],
        "notes": ["Document-management companion to the assessment workflow."],
    },
}


def render_page_description(page_file: str) -> None:
    doc = PAGE_DESCRIPTIONS.get(Path(page_file).name)
    if not doc:
        return

    st.caption(doc["summary"])

    with st.expander("Page guide", expanded=False):
        st.markdown(f"**Purpose**\n\n{doc['purpose']}")

        workflow = doc.get("workflow", [])
        if workflow:
            st.markdown("**Workflow**")
            for step in workflow:
                st.markdown(f"- {step}")

        data_points = doc.get("data", [])
        if data_points:
            st.markdown("**Primary files / services**")
            for item in data_points:
                st.markdown(f"- {item}")

        notes = doc.get("notes", [])
        if notes:
            st.markdown("**Notes**")
            for note in notes:
                st.markdown(f"- {note}")

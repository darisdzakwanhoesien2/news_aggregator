from pathlib import Path

import streamlit as st


PAGE_DESCRIPTIONS = {
    "0_0_0_0_0_0_verification_viewer.py": {
        "summary": "Open and inspect individual verification outputs produced by the ESG scoring pipeline.",
        "purpose": "Use this page for record-level QA when you want to read one verification artifact in detail rather than looking at aggregate dashboards.",
        "workflow": [
            "Select a saved verification payload.",
            "Review answer-level evidence and scoring details.",
            "Compare the stored output against expected structure or content.",
        ],
        "data": ["Inputs: saved verification JSON files under `new_app/data/` or related session folders"],
        "notes": ["Focused debugging and QA tool for verification artifacts."],
    },
    "0_0_0_0_1_data.py": {
        "summary": "Analytics dashboard for the collected news dataset used by the research workflow.",
        "purpose": "Use this page to understand dataset scale, source mix, and trend behavior before passing data into later cleaning or verification steps.",
        "workflow": [
            "Load saved dataset records.",
            "Aggregate counts by source, sentiment, and time.",
            "Inspect raw rows and export supporting views.",
        ],
        "data": ["Inputs: dataset JSON files in `new_app/data/`"],
        "notes": ["High-level health check for the research data pipeline."],
    },
    "0_0_0_2_Bulk_OCR.py": {
        "summary": "Mistral OCR batch pipeline for PDFs and scanned images.",
        "purpose": "Use this page to upload multiple documents, run OCR through Mistral, and save structured page-level outputs for verification and report generation.",
        "workflow": [
            "Upload PDFs or images.",
            "Send files to Mistral OCR and retrieve page/image outputs.",
            "Store JSON, page markdown, and extracted images per document.",
        ],
        "data": [
            "Inputs: uploaded files plus `MISTRAL_API_KEY`",
            "Outputs: `new_app/data/thesis_dataset/` and OCR logs",
        ],
        "notes": ["Resume-safe batch OCR entry point for the research app."],
    },
    "0_0_1_prompt_generator.py": {
        "summary": "Convert thesis chapter or section outlines into reusable prompt templates.",
        "purpose": "Use this page to turn a structured research outline into prompt-ready templates for section drafting or LLM-assisted report generation.",
        "workflow": [
            "Paste or upload chapter structure information.",
            "Parse the hierarchy into reusable sections.",
            "Export generated prompt templates or metadata.",
        ],
        "data": ["Outputs: prompt or template files under `new_app/output/` or `new_app/pages/documentation_*`"],
        "notes": ["Supports the reporting and thesis-writing workflow."],
    },
    "10_mcq_llm_verification.py": {
        "summary": "Main MCQ plus OCR plus LLM verification workflow for ESG scoring.",
        "purpose": "Use this page to select company answers, combine them with OCR evidence, call an LLM verifier, and calculate structured ESG results.",
        "workflow": [
            "Choose the company and answer file.",
            "Assemble OCR evidence from stored documents.",
            "Run LLM verification and export scored results.",
        ],
        "data": [
            "Inputs: answer JSON, OCR text, OpenRouter or configured LLM API",
            "Outputs: verification JSON, score tables, downloadable results",
        ],
        "notes": ["Core research verification page."],
    },
    "10_v3_mcq_llm_verification.py": {
        "summary": "Version 3 MCQ verification workflow with OCR post-processing controls.",
        "purpose": "Use this page when you need the newer verification flow that adds extra cleanup and post-processing steps around OCR evidence.",
        "workflow": [
            "Load answer and OCR sources.",
            "Review or refine OCR text before verification.",
            "Run the LLM verifier and compare scored outputs.",
        ],
        "data": ["Inputs: OCR outputs and answer files in `new_app/data/`"],
        "notes": ["Updated variant of the main verification workflow."],
    },
    "11_research_map.py": {
        "summary": "Reserved page for future research-map or workflow-navigation content.",
        "purpose": "This page can serve as a hub for linking datasets, experiment outputs, and documentation once the research mapping flow is finalized.",
        "workflow": [
            "Use this placeholder to document future research navigation.",
            "Point users to active data, OCR, verification, and reporting pages.",
        ],
        "data": ["Current file is intentionally minimal and acts as a placeholder."],
        "notes": ["Safe location for future roadmap or experiment-index content."],
    },
    "11_v3_mcq_llm_verification.py": {
        "summary": "Another V3 verification page focused on staged MCQ scoring with OCR review.",
        "purpose": "Use this page for the newer staged verification flow that emphasizes selectable OCR sources and scored result packaging.",
        "workflow": [
            "Select company answers.",
            "Pick OCR source files and review extracted evidence.",
            "Run verification and inspect pillar totals plus exports.",
        ],
        "data": ["Inputs: company answer files, OCR artifacts, LLM API configuration"],
        "notes": ["Variant intended for iterative comparison against earlier verification pages."],
    },
    "12_research_structure.py": {
        "summary": "Research documentation browser for thesis structure and prompt strategy comparisons.",
        "purpose": "Use this page to review generated documentation sections and compare drafting strategies such as zero-shot, few-shot, and chain-of-thought.",
        "workflow": [
            "Browse saved documentation assets.",
            "Open generated structure files and prompt outputs.",
            "Compare alternative writing strategies for the same section.",
        ],
        "data": ["Inputs: markdown files in `new_app/pages/documentation_*`"],
        "notes": ["Documentation and analysis companion to the report generator."],
    },
    "1_news_scrapper.py": {
        "summary": "Primary ESG news extractor for the research pipeline.",
        "purpose": "Use this page to collect ESG-related news articles, inspect the feed, and scrape article bodies for later cleaning and analysis.",
        "workflow": [
            "Load or collect news candidates.",
            "Filter and scrape article content.",
            "Persist the extracted records into the research data store.",
        ],
        "data": ["Outputs: news dataset and content files under `new_app/data/`"],
        "notes": ["Main news ingestion page inside `new_app`."],
    },
    "1_news_scrapper_completed.py": {
        "summary": "Completed or refined version of the research news extractor.",
        "purpose": "Use this page when you want the stabilized variant of the news extraction workflow with the latest data-handling adjustments.",
        "workflow": [
            "Load candidate articles.",
            "Scrape article content and persist outputs.",
            "Inspect extracted rows before further processing.",
        ],
        "data": ["Outputs: research news dataset files under `new_app/data/`"],
        "notes": ["Alternative to the primary extractor for comparison or validation."],
    },
    "1_news_scrapper_missing.py": {
        "summary": "Recovery workflow for articles that are missing extracted content.",
        "purpose": "Use this page to revisit partially processed news records and fill in article text that earlier runs missed.",
        "workflow": [
            "Load saved articles with missing or incomplete content.",
            "Retry content scraping and inspection.",
            "Write repaired results back to the dataset.",
        ],
        "data": ["Inputs: saved news dataset and partial content outputs"],
        "notes": ["Useful after interrupted or low-yield extraction runs."],
    },
    "1_news_scrapper_missing_v2.py": {
        "summary": "Second-pass recovery page for unresolved or failed news extractions.",
        "purpose": "Use this page when the first missing-content recovery workflow still leaves incomplete articles and you need another retry path.",
        "workflow": [
            "Load unresolved article rows.",
            "Retry resolution and extraction with updated logic.",
            "Save repaired article content and review the results.",
        ],
        "data": ["Outputs: refreshed article content inside the research data store"],
        "notes": ["Iteration on the missing-content recovery workflow."],
    },
    "2_Content_Viewer.py": {
        "summary": "Inspect scraped news content, URL resolution status, and record details.",
        "purpose": "Use this page to audit whether URLs resolved correctly and whether extracted content looks usable before running downstream cleaning or modeling.",
        "workflow": [
            "Load saved news content records.",
            "Review summary metrics and URL resolution status.",
            "Open detailed comparisons for individual rows.",
        ],
        "data": ["Inputs: news content files under `new_app/data/`"],
        "notes": ["QA page for collected news content."],
    },
    "3_Content_Cleaner.py": {
        "summary": "Normalize and clean raw news article text before further analysis.",
        "purpose": "Use this page to remove boilerplate, inspect before/after changes, and save a cleaner text corpus for later modeling or reporting.",
        "workflow": [
            "Load raw extracted article text.",
            "Apply cleaning rules and preview differences.",
            "Save cleaned content and export the results.",
        ],
        "data": ["Outputs: cleaned text files such as `data/extra_text.json`"],
        "notes": ["Natural follow-up after content extraction QA."],
    },
    "4_chatbot_llm_prompts.py": {
        "summary": "Prompt-oriented chatbot workspace for interacting with the research knowledge base.",
        "purpose": "Use this page when you want to test or tune prompt behavior while chatting against uploaded research context.",
        "workflow": [
            "Configure API key, model, and prompt-related settings.",
            "Load knowledge-base content.",
            "Run multi-turn chat experiments and save conversations.",
        ],
        "data": ["Inputs: LLM API credentials and local knowledge-base files"],
        "notes": ["Prompt experimentation variant of the chatbot."],
    },
    "5_chatbot_llm.py": {
        "summary": "General chatbot workspace backed by the local research knowledge base.",
        "purpose": "Use this page for interactive Q&A over uploaded documents, OCR outputs, or generated reports without editing prompt templates directly.",
        "workflow": [
            "Set API key and model.",
            "Choose knowledge-base sources.",
            "Run and save chat conversations.",
        ],
        "data": ["Outputs: chat history files under `new_app/data/chat_history/`"],
        "notes": ["Standard chatbot interface for the research app."],
    },
    "6_Report_Generator.py": {
        "summary": "Generate ESG research reports and LaTeX sections from stored project assets.",
        "purpose": "Use this page to build report structure, draft sections with an LLM, and export publication-oriented LaTeX output.",
        "workflow": [
            "Generate or edit the report structure.",
            "Draft sections with the configured model.",
            "Compile and export LaTeX-ready report artifacts.",
        ],
        "data": ["Outputs: prompt artifacts and report state files under `new_app/output/` and `new_app/reports/`"],
        "notes": ["Main writing and compilation workflow for the research app."],
    },
    "7_mcq_verification.py": {
        "summary": "Combined ESG pipeline with multiple verification stages in one page.",
        "purpose": "Use this page to run a broader experiment that combines classification, aspect analysis, and structured LLM extraction in sequence.",
        "workflow": [
            "Configure global settings and pipeline toggles.",
            "Run each stage of the ESG analysis stack.",
            "Compare stage outputs in one consolidated interface.",
        ],
        "data": ["Inputs: news content plus configured ML or LLM backends"],
        "notes": ["Broader experimental pipeline than the focused MCQ pages."],
    },
    "7_mcq_verification_clean.py": {
        "summary": "Cleaned ESG-SME MCQ verification workflow with stronger results browsing.",
        "purpose": "Use this page for a more polished ESG-SME verification experience, including uploads, scoring summaries, and run comparisons.",
        "workflow": [
            "Upload company documents for OCR use.",
            "Run LLM-based MCQ verification.",
            "Inspect summaries, comparisons, and question-level details.",
        ],
        "data": ["Outputs: verification runs, score summaries, and comparison views"],
        "notes": ["Cleaner presentation of the ESG-SME verification flow."],
    },
    "7_mcq_verification_v2.py": {
        "summary": "Interactive ESG-SME verification pipeline with questionnaire and run comparison tools.",
        "purpose": "Use this page when you need the questionnaire-driven MCQ workflow and want to compare multiple verification runs side by side.",
        "workflow": [
            "Fill or load ESG-SME answers.",
            "Upload evidence documents and run verification.",
            "Inspect summaries and compare result sets.",
        ],
        "data": ["Inputs: questionnaire answers, OCR documents, LLM configuration"],
        "notes": ["Versioned successor to the earlier ESG-SME workflow."],
    },
    "8_generative_report_image.py": {
        "summary": "Chatbot and diagram-generation workspace for report visuals.",
        "purpose": "Use this page to chat with the project knowledge base and generate diagram-style images or visual support content for reports.",
        "workflow": [
            "Configure model and knowledge-base settings.",
            "Run research chat interactions.",
            "Generate report diagrams from textual instructions.",
        ],
        "data": ["Inputs: LLM API settings and optional visual-generation prompts"],
        "notes": ["Visual-support companion to the main report generator."],
    },
    "9_testing_ocr_verification.py": {
        "summary": "Sandbox page for testing OCR-driven verification ideas before promotion to the main workflow.",
        "purpose": "Use this page to validate new OCR verification logic or prompt behavior on a smaller experimental surface.",
        "workflow": [
            "Load OCR outputs and candidate prompts.",
            "Run test verification calls.",
            "Inspect the resulting artifacts before merging changes elsewhere.",
        ],
        "data": ["Inputs: OCR outputs and draft prompt logic"],
        "notes": ["Experimental verification page."],
    },
    "verification_dashboard.py": {
        "summary": "Aggregate dashboard for verification files across research sessions.",
        "purpose": "Use this page to summarize verification output volumes, company coverage, score trends, and status distributions across many saved runs.",
        "workflow": [
            "Scan the workspace for saved `verification.json` files.",
            "Build per-file and per-verification summary tables.",
            "Visualize status and pillar distributions.",
        ],
        "data": ["Inputs: saved verification artifacts across the workspace"],
        "notes": ["Best page for cross-run verification monitoring."],
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

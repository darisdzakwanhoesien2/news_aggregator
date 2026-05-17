# `new_app` Research Workflow

`new_app/` is the research and experimentation workspace in this repository. It focuses on OCR, ESG MCQ verification, chat-based exploration, and report generation.

## Entry Point

Run:

```bash
streamlit run new_app/app.py
```

The landing page explains the major page groups and points users to the active workflows in the sidebar.

## Primary Workflows

### 1. News ingestion and cleanup

- `pages/1_news_scrapper.py`
- `pages/1_news_scrapper_completed.py`
- `pages/1_news_scrapper_missing.py`
- `pages/1_news_scrapper_missing_v2.py`
- `pages/2_Content_Viewer.py`
- `pages/3_Content_Cleaner.py`
- `pages/0_0_0_0_1_data.py`

Use these pages to collect news, repair incomplete extractions, inspect URLs, and clean article text before downstream modeling.

### 2. OCR pipeline

- `pages/0_0_0_2_Bulk_OCR.py`
- `pages/9_testing_ocr_verification.py`

The main OCR path uploads PDFs or images to Mistral, saves page markdown and images, and persists structured OCR JSON under `new_app/data/`.

### 3. Verification and scoring

- `pages/7_mcq_verification.py`
- `pages/7_mcq_verification_clean.py`
- `pages/7_mcq_verification_v2.py`
- `pages/10_mcq_llm_verification.py`
- `pages/10_v3_mcq_llm_verification.py`
- `pages/11_v3_mcq_llm_verification.py`
- `pages/0_0_0_0_0_0_verification_viewer.py`
- `pages/verification_dashboard.py`

These pages compare answer sets against OCR evidence, run LLM verification, calculate structured scores, and summarize saved verification artifacts.

### 4. Prompting, documentation, and report generation

- `pages/0_0_1_prompt_generator.py`
- `pages/12_research_structure.py`
- `pages/6_Report_Generator.py`
- `pages/11_research_map.py`

These pages support thesis structure generation, prompt authoring, markdown documentation review, and LaTeX report construction.

### 5. Chat and exploratory interfaces

- `pages/4_chatbot_llm_prompts.py`
- `pages/5_chatbot_llm.py`
- `pages/8_generative_report_image.py`

These pages provide knowledge-base chat and, in the visual variant, report-support diagram generation.

## Important Directories

| Path | Role |
| --- | --- |
| `new_app/data/` | OCR inputs, company folders, chat history, and research datasets |
| `new_app/logs/` | OCR and workflow logs |
| `new_app/output/prompt/` | Generated prompt sections and related artifacts |
| `new_app/reports/` | Report state and generated report metadata |
| `new_app/pages/documentation_*` | Saved documentation or thesis-support markdown files |

## External Services

| Service | Variable | Where used |
| --- | --- | --- |
| Mistral OCR | `MISTRAL_API_KEY` | Bulk OCR pages |
| OpenRouter | `OPENROUTER_API_KEY` | Verification and chatbot pages |
| OpenRouter endpoint overrides | `OPENROUTER_API_URL`, `OPENROUTER_MODELS_URL` | Verification pages |

## Recommended Working Order

1. OCR source documents with `0_0_0_2_Bulk_OCR.py`.
2. Collect or clean supporting news text if the experiment uses external articles.
3. Run the relevant verification page for the target experiment generation.
4. Audit results with the verification viewer or dashboard.
5. Summarize the output through the report generator or documentation pages.

## Notes

- The `new_app` pages are more experimental than the public portal and include multiple versioned verification workflows.
- Several files preserve iterative research variants side by side. The in-page `Page guide` panels document the intended role of each page.

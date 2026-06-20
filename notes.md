# News Aggregator Repository

This repository contains three separate Streamlit applications plus shared scraping, OCR, storage, and verification utilities:

1. The root app is a news and social-media monitoring workspace for Indonesian news, Instagram, X, and YouTube.
2. `new_app/` is a research-oriented workflow for OCR, ESG MCQ verification, chat, and report generation.
3. `public_account/` is a user-facing portal for registration, document upload, and scored ESG assessments.

The codebase also includes historical prototypes and archived page variants. The active page files now expose in-app `Page guide` sections to explain their purpose, inputs, outputs, and operational notes.

## App Map

| App | Entry point | Purpose |
| --- | --- | --- |
| Root monitoring app | `app.py` | News collection, dataset management, dashboards, and social-media scraping |
| Alternative root app | `app_2.py` | Standalone robust article scraper for URL and CSV-driven extraction |
| Research workflow | `new_app/app.py` | OCR, verification experiments, chat, and report generation |
| Public portal | `public_account/app.py` | Authentication, user sessions, uploads, and ESG assessment flows |

## Repository Structure

| Path | Role |
| --- | --- |
| `pages/` | Active Streamlit pages for the root monitoring app |
| `new_app/pages/` | Research and thesis-support pages |
| `public_account/pages/` | User-facing portal pages |
| `extractor/` | Article extraction pipeline, redirect resolution, and JSON helpers |
| `ingestors/` | Platform-specific ingestion for X and YouTube |
| `scrapers/` | Older scraper abstractions and `snscrape`-based X flow |
| `utils/` | Shared helpers for Instagram, YouTube, storage, media rendering, and metric parsing |
| `data/`, `logs/` | Root app datasets, logs, and derived outputs |
| `new_app/data/`, `new_app/logs/`, `new_app/output/`, `new_app/reports/` | Research app working data |
| `public_account/user_data/` | User-scoped uploads, OCR outputs, verification artifacts, and session metadata |

## How To Run

From the repository root:

```bash
streamlit run app.py
```

Research workflow:

```bash
streamlit run new_app/app.py
```

Public portal:

```bash
streamlit run public_account/app.py
```

## Environment Variables

The repository uses multiple external services. These variables are referenced directly in code:

| Variable | Used by | Purpose |
| --- | --- | --- |
| `MISTRAL_API_KEY` | `new_app/pages/0_0_0_2_Bulk_OCR.py`, related OCR flows | Bulk OCR on PDFs and images |
| `OPENROUTER_API_KEY` | `new_app/pages/*verification*`, chatbot pages, public-account assessment pages | LLM-backed verification and chat |
| `OPENROUTER_API_URL` | Verification pages | Optional OpenRouter endpoint override |
| `OPENROUTER_MODELS_URL` | Verification pages | Optional model-list endpoint override |
| `YOUTUBE_API_KEY` | `pages/8_YouTube_Scraper.py`, `utils/youtube_utils.py` | YouTube channel, video, and comment ingestion |
| `X_BEARER_TOKEN` | `ingestors/x_api_ingestor.py` | Official X API collection mode |

## Dependency Notes

The checked-in root `requirements.txt` only lists a small subset of the libraries used across the repository. The code additionally references packages such as:

- `beautifulsoup4`
- `dotenv` / `python-dotenv`
- `instaloader`
- `lxml`
- `newspaper3k`
- `playwright`
- `plotly`
- `altair`
- `trafilatura`
- `snscrape`

If you want a reproducible environment, create separate requirement files per app or consolidate the imports into one locked environment definition.

## Documentation Index

- Root monitoring app: [README_news_extractor.md](README_news_extractor.md)
- Research workflow: [new_app/README.md](new_app/README.md)
- Public portal: [public_account/README.md](public_account/README.md)

## Operational Notes

- Many page files contain commented historical implementations. Those are preserved for reference and should not be assumed to be production-ready.
- The repository currently stores most datasets as JSON rather than in a database.
- Authentication in `public_account/` is local-file based. It is suitable for internal demos or controlled environments, not hardened production deployment.

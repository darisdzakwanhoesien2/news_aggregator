# `public_account` Portal

`public_account/` is the user-facing Streamlit portal for local authentication, user-scoped document handling, and ESG assessment workflows.

## Entry Point

Run:

```bash
streamlit run public_account/app.py
```

The landing page links users into login, registration, dashboard, and assessment flows.

## Core Features

- Local registration and login backed by JSON files.
- User-scoped file storage in `public_account/user_data/`.
- Session-based ESG assessment workflows.
- OCR plus LLM verification variants and form-only alternatives.
- Saved result review through dashboard and results pages.

## Page Overview

| Page | Purpose |
| --- | --- |
| `pages/01_login.py` | Authenticate existing users and restore session state |
| `pages/02_register.py` | Create new user profiles and hash passwords before storage |
| `pages/03_dashboard.py` | Show personalized metrics, recent sessions, and navigation |
| `pages/04_form_assessment.py` | Full answer + OCR + LLM verification workflow |
| `pages/04_form_assessment_afterLogin.py` | Authenticated full workflow variant |
| `pages/04_form_assessment_withoutPDF.py` | Form-only scoring without OCR or LLM |
| `pages/04_form_assessment_withoutPDF_generalized.py` | Reusable generalized form-only flow |
| `pages/04_form_assessment_withoutPDF_generalized_weightage.py` | Weighted form-only flow |
| `pages/05_results.py` | Open stored result bundles and inspect verification output |
| `pages/ukm_files.py` | Upload and review user-scoped files |

## Data Model

Most data is persisted as JSON or CSV in user-specific folders:

- `public_account/user_data/<username>/metadata.json`
- `public_account/user_data/<username>/sessions/<timestamp>/inputs/`
- `public_account/user_data/<username>/sessions/<timestamp>/outputs/`
- `public_account/user_data/<username>/sessions/<timestamp>/documents/`

Typical session outputs include:

- `answers.json`
- `verification.json`
- `scores.csv`
- OCR page markdown and extracted images

## Authentication Notes

- Credentials are stored locally in JSON files, not in a database.
- Passwords are hashed with PBKDF2 and random salt before they are written to disk.
- Query parameters are used in some flows to preserve user context between pages.

## External Dependencies

The full OCR and verification flows depend on:

- `MISTRAL_API_KEY` for OCR
- `OPENROUTER_API_KEY` and related OpenRouter endpoints for LLM verification

If these are absent, the no-PDF / no-LLM pages remain the fallback option.

## Operational Guidance

1. Register or log in through the landing page.
2. Upload any supporting files from `ukm_files.py` or directly inside an assessment page.
3. Choose the assessment mode:
   - full OCR + LLM verification
   - form-only scoring
4. Review saved results from the dashboard or `05_results.py`.

## Deployment Caution

The portal is designed around local-file persistence. It is suitable for controlled demos or internal workflows, but it is not hardened for concurrent, internet-exposed production use without adding a real database, stronger session handling, and server-side security controls.

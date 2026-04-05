project_root/
│
├── app.py                          # ← your BIG combined script (current code)
│
├── data/                           # ← EXISTING (keep this)
│   ├── <company_name>/
│   │   ├── ocr/
│   │   ├── mcq_answers/
│   │   └── ...
│
├── user_data/                      # 🔥 NEW (core of multi-session system)
│   ├── users.json                  # login + roles
│   │
│   ├── <user_id>/                  # one folder per user
│   │   ├── metadata.json           # file metadata (you already use this)
│   │
│   │   ├── files/                  # uploaded files
│   │   │   ├── raw/                # original uploads
│   │   │   ├── processed/          # OCR outputs / cleaned files
│   │   │
│   │   ├── sessions/               # 🔥 MULTI-SESSION STORAGE
│   │   │   ├── 20260405T101500Z/   # session_id = timestamp
│   │   │   │   ├── config.json
│   │   │   │   ├── answers.json
│   │   │   │   ├── verification.json
│   │   │   │   ├── scores.csv
│   │   │   │   ├── raw_llm.txt
│   │   │   │
│   │   │   ├── 20260405T103200Z/
│   │   │
│   │   ├── history.json           # optional aggregated results
│
├── config/
│   ├── settings.py                 # API keys fallback
│
├── .env
├── requirements.txt
└── README.md
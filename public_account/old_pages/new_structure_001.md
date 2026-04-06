You’re essentially building a **multi-tenant, session-aware, document-heavy LLM system** — and since you want a *single long script*, the structure must compensate by being **very strong at the filesystem level**.

Below is a **realistic, production-grade directory structure** tailored to your exact behavior:

* 5 users
* Each user has 2–4 sessions
* Each session has **different uploaded PDFs**
* Each PDF produces its own **OCR bundle (dataset + processed pages)**
* Fully aligned with your script logic (`thesis_pdf`, `thesis_dataset`, session outputs, etc.)

---

# 🧠 Key Design Principles (Before Structure)

### 1. Session = Atomic Unit

Each session is:

* Independent
* Has its own PDFs
* Has its own OCR outputs
* Has its own LLM results

👉 This avoids cross-contamination (VERY important)

---

### 2. Each PDF = Its Own OCR Bundle

Instead of:

```
session → 1 OCR
```

We use:

```
session → multiple PDFs → multiple OCR bundles
```

---

### 3. No Shared OCR Across Sessions

Even if same PDF appears twice:

* treat it as separate (real-world behavior)
* avoids debugging nightmare

---

# 🏗️ FULL REALISTIC PROJECT STRUCTURE

```
project_root/
│
├── app.py                          # 🔥 Your single long Streamlit script
│
├── data/                           # 🔒 GLOBAL / SHARED
│   ├── esg_mcq.json
│
│   ├── thesis_pdf/                 # 🔥 TEMP UPLOADS (ALL USERS)
│   │   ├── user_001_20260405T101500Z/
│   │   │   ├── sustainability_report.pdf
│   │   │   ├── annual_report.pdf
│   │   │
│   │   ├── user_002_20260405T111000Z/
│   │   │   ├── esg_statement.pdf
│
│   ├── thesis_dataset/             # 🔥 OCR OUTPUT (GLOBAL POOL)
│   │
│   │   ├── bundle_user001_sessA_doc1/
│   │   │   ├── ocr_result.json
│   │   │   ├── pages/
│   │   │   │   ├── page_0001.md
│   │   │   │   ├── page_0002.md
│   │   │   ├── images/
│   │   │
│   │   ├── bundle_user001_sessA_doc2/
│   │   ├── bundle_user002_sessB_doc1/
│
│
├── user_data/                      # 🔥 CORE USER SYSTEM
│   ├── users.json
│
│   ├── user_001/
│   │   ├── profile.json
│   │   ├── history.json
│   │
│   │   ├── sessions/
│   │   │
│   │   │   ├── 20260405T101500Z/   # SESSION 1
│   │   │   │
│   │   │   ├── metadata.json
│   │   │   │
│   │   │   ├── inputs/
│   │   │   │   ├── answers.json
│   │   │   │   ├── config.json
│   │   │   │
│   │   │   ├── documents/          # 🔥 KEY DESIGN
│   │   │   │
│   │   │   │   ├── doc_001/
│   │   │   │   │   ├── original/
│   │   │   │   │   │   ├── sustainability_report.pdf
│   │   │   │   │   │
│   │   │   │   │   ├── ocr/
│   │   │   │   │   │   ├── ocr_result.json
│   │   │   │   │   │   ├── pages/
│   │   │   │   │   │   ├── images/
│   │   │   │   │   │
│   │   │   │   │   ├── metadata.json
│   │   │   │   │       # filename, size, upload_time, hash
│   │   │   │
│   │   │   │   ├── doc_002/
│   │   │   │       ├── original/
│   │   │   │       ├── ocr/
│   │   │   │       ├── metadata.json
│   │   │
│   │   │   ├── processing/
│   │   │   │   ├── combined_ocr.txt
│   │   │   │   ├── cleaned_ocr.txt
│   │   │   │   ├── chunks.json
│   │   │   │   ├── embeddings.pkl
│   │   │
│   │   │   ├── outputs/
│   │   │   │   ├── verification.json
│   │   │   │   ├── scores.csv
│   │   │   │   ├── raw_llm.txt
│   │   │   │   ├── summary.txt
│   │   │
│   │   │   ├── logs/
│   │   │   │   ├── api_calls.log
│   │   │   │   ├── errors.log
│   │
│   │   │   ├── 20260406T140200Z/   # SESSION 2
│   │   │   ├── 20260407T093000Z/   # SESSION 3
│   │
│   │   ├── files/                 # 🔁 USER GLOBAL FILES
│   │   │   ├── raw/
│   │   │   ├── metadata.json
│
│
│   ├── user_002/
│   │   ├── sessions/
│   │   │   ├── 20260405T111000Z/
│   │   │   ├── 20260406T120000Z/
│
│   ├── user_003/
│   ├── user_004/
│   ├── user_005/
│
│
├── logs/                          # 🔥 GLOBAL LOGGING
│   ├── system.log
│   ├── errors.log
│   ├── api_usage.log
│
├── config/
│   ├── settings.py
│
├── .env
├── requirements.txt
└── README.md
```

---

# 🔥 WHAT THIS SOLVES (IMPORTANT)

## ✅ 1. Multiple PDFs per session

```
session/
  ├── documents/
      ├── doc_001/
      ├── doc_002/
```

---

## ✅ 2. Each PDF has its own OCR

```
doc_001/
  ├── original/
  ├── ocr/
```

---

## ✅ 3. You can merge OCR later

```
processing/
  ├── combined_ocr.txt
```

👉 Matches your `collect_ocr_text()` logic

---

## ✅ 4. Clean separation of concerns

| Layer         | Purpose           |
| ------------- | ----------------- |
| `documents/`  | raw + OCR         |
| `processing/` | cleaned + chunked |
| `outputs/`    | LLM results       |
| `logs/`       | debugging         |

---

# 📊 REALISTIC EXAMPLE (1 USER, 2 SESSIONS)

```
user_001/
  sessions/

    20260405T101500Z/
      documents/
        doc_001 → sustainability_report.pdf
        doc_002 → annual_report.pdf

    20260406T140200Z/
      documents/
        doc_001 → new_esg_report.pdf
```

---

# ⚠️ CRITICAL DESIGN DECISIONS (FROM EXPERIENCE)

## ❌ BAD (what most people do)

```
session/
  ├── ocr/
```

👉 Problem:

* multiple PDFs overwrite each other
* impossible to debug

---

## ✅ GOOD (your design now)

```
session/
  ├── documents/
      ├── doc_001/
      ├── doc_002/
```
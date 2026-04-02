Yes — and that’s actually a **very smart move**.

Starting with the **Interactive Questionnaire first** lets you:

* Validate your **ESG MCQ design**
* Collect **ground-truth / human-labeled data**
* Debug **UX + data schema**
* Later plug in OCR + LLM as *automation layers*

Let’s restructure your app into a **clean, production-ready Streamlit app** with:

> ✅ Interactive Questionnaire FIRST (primary entry point)
> ➕ Then OCR
> ➕ Then LLM auto-fill
> ➕ Then comparison

---

# ✅ 1. NEW APP STRUCTURE (CLEAN)

```
new_app/
│
├── app.py                      # Main router (multi-page)
├── pages/
│   ├── 1_Interactive_QA.py     # ✅ START HERE
│   ├── 2_OCR_Upload.py
│   ├── 3_LLM_Auto_MCq.py
│   ├── 4_Results_Viewer.py
│
├── utils/
│   ├── io.py
│   ├── ocr.py
│   ├── llm.py
│   ├── prompts.py
│
├── data/
│   ├── esg_mcq.json
│   └── <company_name>/
│
├── .env
```

---

# 🚀 2. MAIN ENTRY (`app.py`)

```python
import streamlit as st

st.set_page_config(
    page_title="ESG-SME Verifier",
    page_icon="📋",
    layout="wide"
)

st.title("📋 ESG-SME Verification Platform")

st.markdown("""
### 🔍 Workflow

1. **🧠 Interactive Questionnaire (START HERE)**
2. 📤 Upload Documents (OCR)
3. 🤖 Run LLM Auto Verification
4. 📊 Compare Results

---

### 🎯 Goal
Build **auditable ESG scoring** with:
- Human baseline
- AI automation
- Evidence traceability
""")
```

---

# 🧠 3. INTERACTIVE QUESTIONNAIRE (CORE PAGE)

## 📄 `pages/1_Interactive_QA.py`

This is your **NEW PRIMARY INTERFACE**

```python
import streamlit as st
import json
from pathlib import Path
from datetime import datetime
import re

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

ESG_FILE = DATA_DIR / "esg_mcq.json"


# ─────────────────────────────────────────────
# Load Questions
# ─────────────────────────────────────────────
def load_questions():
    if ESG_FILE.exists():
        return json.loads(ESG_FILE.read_text())
    return []


ESG_MCQ = load_questions()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def safe_name(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def save_answers(company, answers):
    out_dir = DATA_DIR / company / "mcq_answers"
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{ts}_manual.json"

    record = {
        "company": company,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "mode": "manual",
        "answers": answers
    }

    path.write_text(json.dumps(record, indent=2))
    return path


# ─────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────
st.title("🧠 ESG Interactive Questionnaire")

# Company selection
companies = [d.name for d in DATA_DIR.iterdir() if d.is_dir()]

col1, col2 = st.columns(2)

with col1:
    selected = st.selectbox("Select Company", ["(new)"] + companies)

with col2:
    if selected == "(new)":
        new_company = st.text_input("New Company Name")
        company = safe_name(new_company) if new_company else None
    else:
        company = selected


if not company:
    st.warning("Please create/select a company")
    st.stop()


st.success(f"📁 Working on: {company}")


# ─────────────────────────────────────────────
# Questionnaire
# ─────────────────────────────────────────────
answers = []

with st.form("mcq_form"):
    for q in ESG_MCQ:
        with st.expander(f"{q['id']} — {q['question']}"):
            selected = st.radio(
                "Answer",
                ["", *q["choices"].keys()],
                key=f"{q['id']}_choice",
                horizontal=True
            )

            evidence = st.text_area(
                "Evidence (optional)",
                key=f"{q['id']}_evidence"
            )

            confidence = st.selectbox(
                "Confidence",
                ["High", "Medium", "Low"],
                key=f"{q['id']}_conf"
            )

            answers.append({
                "id": q["id"],
                "pillar": q["pillar"],
                "question": q["question"],
                "selected": selected,
                "selected_text": q["choices"].get(selected, ""),
                "evidence": evidence,
                "confidence": confidence
            })

    submitted = st.form_submit_button("💾 Save Answers")


if submitted:
    path = save_answers(company, answers)
    st.success(f"Saved to {path}")
    st.json(answers)
```

---

# 📊 4. WHY THIS APPROACH IS BETTER

## 🔥 You now have:

### 1. Ground Truth Dataset

* Human-labeled ESG answers
* Evidence included
* Confidence included

### 2. Training Data for:

* Fine-tuning LLM
* Evaluation benchmark
* ESG scoring calibration

### 3. Explainability (CRITICAL for ESG)

Every answer has:

```json
{
  "selected": "B",
  "evidence": "Company reports carbon emissions annually",
  "confidence": "High"
}
```

👉 This solves your research gap:

> ❗ "ESG lacks explainability"

---

# 🧠 5. NEXT STEP (AFTER THIS)

Once this works, we plug in:

## ➕ Step 2: OCR

* Same as your existing code (modularize it)

## ➕ Step 3: LLM AUTO MODE

We modify your pipeline:

```python
AUTO vs HUMAN vs HYBRID
```

| Mode   | Description            |
| ------ | ---------------------- |
| Manual | Human answers          |
| Auto   | LLM answers            |
| Hybrid | LLM + human correction |

---

# 🚀 6. ADVANCED (WHAT YOU CAN BUILD NEXT)

### 🔬 Research-grade features:

* Inter-rater agreement (human vs LLM)
* ESG scoring aggregation
* Confidence-weighted scoring
* SDG alignment mapping
* Knowledge graph linking

---

# 💡 FINAL TAKE

Starting with **Interactive Questionnaire first** is exactly how you:

> 👉 Turn this from a tool → into a **PhD-level ESG system**

Because now you’re building:

* Dataset
* Evaluation benchmark
* Explainable pipeline

---

# 👉 Next step?

I can help you upgrade this into:

### 1. 🔥 Hybrid AI (LLM suggests + human approves)

### 2. 📊 ESG scoring engine (weighted scoring)

### 3. 🧠 Knowledge graph integration (your thesis direction)

Just tell me:

> “Next: hybrid mode” or “Next: scoring system”

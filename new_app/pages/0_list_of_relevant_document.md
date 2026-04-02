https://chatgpt.com/c/69ccf181-e458-8322-b3f9-224a767c7070

To support your ESG–SME MCQ verification pipeline, you need **traceable, auditable document sources** mapped to each question. Below is a **clean, production-ready table** linking each ESG question to the **most relevant supporting documents** (ideal for OCR + RAG + LLM verification).

---

# 📊 ESG Questions → Supporting Documents Mapping

## 🌱 Environmental (E01–E10)

| Code | Question (Short)                 | Key Supporting Documents                                                                |
| ---- | -------------------------------- | --------------------------------------------------------------------------------------- |
| E01  | GHG emissions tracking           | Sustainability Report, Carbon Disclosure (CDP), ESG Report, Annual Report (ESG section) |
| E02  | Carbon / net-zero targets        | Net Zero Strategy, Climate Action Plan, Sustainability Report                           |
| E03  | Energy consumption monitoring    | Energy Reports, Sustainability Report, ISO 50001 Documentation                          |
| E04  | Renewable energy share           | Sustainability Report, Energy Mix Disclosure, ESG Report                                |
| E05  | Water management                 | Water Stewardship Policy, Sustainability Report, Environmental Report                   |
| E06  | Waste management                 | Waste Management Policy, ESG Report, Environmental Metrics Disclosure                   |
| E07  | Climate risk assessment          | TCFD Report, Risk Management Report, Annual Report (Risk Section)                       |
| E08  | Environmental policy / ISO 14001 | Environmental Policy Document, ISO 14001 Certificate                                    |
| E09  | Supplier environmental criteria  | Supplier Code of Conduct, Procurement Policy, ESG Policy                                |
| E10  | Environmental disclosure         | Annual Report, Sustainability Report, Integrated Report                                 |

---

## 👥 Social (S01–S10)

| Code | Question (Short)             | Key Supporting Documents                              |
| ---- | ---------------------------- | ----------------------------------------------------- |
| S01  | Health & safety policy       | H&S Policy, Employee Handbook, ESG Report             |
| S02  | Injury / accident tracking   | Safety Reports, ESG Metrics Disclosure, Annual Report |
| S03  | Training programmes          | HR Policy, Learning & Development Reports             |
| S04  | DEI policy                   | Diversity Policy, ESG Report, HR Policy               |
| S05  | Employee engagement          | Employee Survey Reports, HR Analytics Reports         |
| S06  | Living wage                  | Compensation Policy, HR Policy, Sustainability Report |
| S07  | Community engagement         | CSR Report, Sustainability Report                     |
| S08  | Human rights / labour policy | Human Rights Policy, Supplier Code of Conduct         |
| S09  | Customer satisfaction        | Customer Feedback Reports, NPS Reports                |
| S10  | Parental leave / flexibility | HR Policy, Employee Benefits Documentation            |

---

## 🏛️ Governance (G01–G10)

| Code | Question (Short)             | Key Supporting Documents                         |
| ---- | ---------------------------- | ------------------------------------------------ |
| G01  | ESG oversight body           | Corporate Governance Report, Board Charter       |
| G02  | Code of conduct              | Code of Ethics Document                          |
| G03  | Anti-corruption policy       | Anti-Bribery Policy, Compliance Policy           |
| G04  | Whistleblower mechanism      | Whistleblowing Policy                            |
| G05  | Data privacy / cybersecurity | Data Protection Policy, IT Security Policy       |
| G06  | Independent audit            | Financial Statements, Auditor Report             |
| G07  | Ownership disclosure         | Annual Report, Corporate Governance Report       |
| G08  | ESG standards alignment      | Sustainability Report (GRI / SASB / SDG mapping) |
| G09  | Risk management framework    | Enterprise Risk Management (ERM) Report          |
| G10  | ESG targets tracking         | ESG Scorecards, Sustainability Report            |

---

# 🧠 How to Use This in Your Pipeline

### 1. Document Retrieval Layer (OCR Step)

Map company files into structured folders:

```
data/
  └── company_name/
        ├── sustainability_report.pdf
        ├── annual_report.pdf
        ├── code_of_conduct.pdf
        ├── risk_report.pdf
```

---

### 2. Retrieval-Augmented Generation (RAG)

For each question:

* Query only **relevant document types**
* Example:

```python
query_docs = {
  "E01": ["sustainability", "cdp", "esg"],
  "G03": ["anti-corruption", "compliance"],
}
```

---

### 3. LLM Prompt Strategy (1-shot)

Inject:

* Question
* Extracted text chunks from **relevant documents only**

---

### 4. Explainability Layer (VERY IMPORTANT for your thesis)

Store:

* Source document
* Page number
* Extracted evidence snippet

Example output:

```json
{
  "question": "E01",
  "answer": "Yes",
  "confidence": 0.92,
  "evidence": "The company reports Scope 1, 2, and 3 emissions...",
  "source": "Sustainability_Report_2023.pdf",
  "page": 45
}
```

---

# 🚀 Pro Insight (PhD-Level Improvement)

You can significantly strengthen your system by mapping documents to **ESG frameworks**:

| Framework | Documents               |
| --------- | ----------------------- |
| GRI       | Sustainability Report   |
| TCFD      | Climate Risk Report     |
| SASB      | Industry ESG Disclosure |
| UN SDGs   | Impact Report           |

This enables:

* **Standardized scoring**
* **Cross-company comparability**
* **Auditability (critical for ESG credibility gap)**

---

# 🔥 If You Want Next Step

I can help you build:

✅ Full **automated document classifier (PDF → ESG category)**
✅ **Chunking + embedding + FAISS retrieval system**
✅ **LLM verification prompt optimized for ESG auditing**
✅ **Streamlit dashboard (your pipeline Step 4 UI)**
✅ **Explainable ESG scoring model (publishable-level)**

Just tell me:
👉 *“Build full ESG verification pipeline code”*

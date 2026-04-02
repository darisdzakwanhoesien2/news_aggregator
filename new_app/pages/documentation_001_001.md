You’re running into a **path resolution mismatch problem** — not a logic bug.

Right now your pipeline assumes:

```
new_app/data/<company_name>/ocr/ocr_result.json
```

But your actual OCR file lives in:

```
new_app/data/thesis_dataset/CSSA ESG support Document 2023_pdf/ocr_result.json
```

And your selected company is:

```
new_app/data/Testing 2/
```

So your app is trying to find OCR inside **Testing 2**, but it only exists in **thesis_dataset/...**

---

# 🔥 Root Cause (Very Important)

Your function:

```python
get_ocr_text(company_dir)
```

ONLY searches **inside the selected company folder**.

But your OCR lives in a **completely different dataset tree**.

So result = ❌ No OCR found → everything becomes `NOT_FOUND`.

---

# ✅ Fix Options (Best → Worst)

## 🥇 Option 1 — Correct Data Structure (Recommended)

Move OCR into the company folder you are analyzing.

### ✅ Do this:

```
new_app/data/Testing 2/ocr/ocr_result.json
```

So full structure becomes:

```
data/
 └── Testing 2/
     ├── mcq_answers/
     │   └── 20260402T025010Z_manual.json
     └── ocr/
         ├── ocr_result.json
         ├── pages/
         └── images/
```

👉 This requires **zero code change** and matches your pipeline design.

---

## 🥈 Option 2 — Add Cross-Folder OCR Linking (Smart Fix)

If you want to reuse OCR across datasets, modify:

### 🔧 `ensure_ocr_for_company()`

Add a mapping rule:

```python
OCR_GLOBAL_DIR = DATA_DIR / "thesis_dataset"

def find_external_ocr(company_name: str):
    for j in OCR_GLOBAL_DIR.rglob("ocr_result.json"):
        if company_name.lower() in str(j).lower():
            return j.parent
    return None
```

Then inject inside `ensure_ocr_for_company()`:

```python
# BEFORE final fallback
external = find_external_ocr(company_dir.name)
if external:
    return external
```

---

## 🥉 Option 3 — Manual OCR Selector in UI (Best UX)

Add a dropdown so user can choose OCR source.

### 🔧 Add in Step 2:

```python
st.subheader("Optional: Select External OCR Source")

all_ocr = list(DATA_DIR.rglob("ocr_result.json"))
ocr_options = [str(p) for p in all_ocr]

selected_ocr = st.selectbox(
    "Select OCR file manually (optional)",
    options=["Auto-detect"] + ocr_options
)

if selected_ocr != "Auto-detect":
    ocr_text = collect_ocr_text(Path(selected_ocr).parent)
```

👉 This is **production-grade UX**.

---

# ⚠️ Hidden Problem You Will Hit Next

Even after fixing paths, your system will still degrade because:

## ❌ You truncate OCR to 14k chars

```python
ocr_snippet = ocr_text[:max_ocr_chars]
```

So:

* Large ESG reports → **most evidence never seen**
* LLM → falsely returns `NOT_FOUND`

---

# 🚀 Critical Upgrade (You SHOULD do this)

## Replace full OCR dump with retrieval

Instead of:

```python
ocr_snippet = ocr_text[:14000]
```

Do:

### Step 1 — Chunk OCR

```python
def chunk_text(text, size=1000, overlap=200):
    chunks = []
    for i in range(0, len(text), size - overlap):
        chunks.append(text[i:i+size])
    return chunks
```

---

### Step 2 — Retrieve relevant chunks per question

```python
def retrieve_relevant_chunks(question, chunks, top_k=5):
    scored = []
    for c in chunks:
        score = sum(word in c.lower() for word in question.lower().split())
        scored.append((score, c))
    scored.sort(reverse=True)
    return [c for _, c in scored[:top_k]]
```

---

### Step 3 — Modify prompt builder

Replace:

```python
OCR DOCUMENT TEXT:
{ocr_snippet}
```

With:

```python
RELEVANT OCR SNIPPETS:
{retrieved_chunks}
```

---

# 🧠 Final Recommendation

Do this combination:

### ✅ MUST

* Move OCR into company folder OR enable external linking

### ✅ SHOULD

* Add manual OCR selector (UI)

### ✅ CRITICAL (for accuracy)

* Replace truncation with retrieval

---

# 🔥 Quick Fix Summary

If you want fastest solution:

```bash
mkdir -p "new_app/data/Testing 2/ocr"
cp "new_app/data/thesis_dataset/CSSA ESG support Document 2023_pdf/ocr_result.json" \
   "new_app/data/Testing 2/ocr/"
```

---

# If you want, I can upgrade your script to:

✅ Retrieval-based verification (RAG)
✅ Multi-call LLM (per question → 10x accuracy)
✅ Evidence grounding with page citations
✅ ESG scoring explainability dashboard

Just say:

> “Upgrade this to production RAG pipeline”

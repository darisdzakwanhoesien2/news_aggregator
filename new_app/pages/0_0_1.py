import json
from pathlib import Path
import streamlit as st

# Simple defaults (matches other pages)
DEFAULT_TEMPLATE_METADATA = {
    "header_prompt": "You are an academic researcher writing a Master's thesis.",
    "title": "Thesis Title: \"Neurosymbolic Reasoning for Robust Greenwashing Detection and Actionable ESG Analysis\""
}

def load_metadata(path: str):
    try:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return DEFAULT_TEMPLATE_METADATA.copy()

def load_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception as e:
        return ""

def parse_markdown_table(md_text: str):
    # collect lines that look like table rows (contain |)
    lines = [ln for ln in md_text.splitlines() if "|" in ln]
    if len(lines) < 3:
        return []
    # assume first line = header, second = separator, rest = rows
    header = lines[0].strip().strip("|")
    cols = [c.strip() for c in header.split("|") if c.strip() != ""]
    rows = []
    for ln in lines[2:]:
        # ignore table separator lines
        if set(ln.strip()) <= set("|- "):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        # pad/trim to column count
        if len(cells) < len(cols):
            cells += [""] * (len(cols) - len(cells))
        cells = cells[: len(cols)]
        rows.append({cols[i]: cells[i] for i in range(len(cols))})
    return rows

def extract_thesis_title(raw: str):
    if not raw:
        return ""
    # try to extract text in quotes
    if '"' in raw:
        parts = raw.split('"')
        if len(parts) >= 3:
            return parts[1].strip()
    # fallback: strip "Thesis Title:" prefix if present
    lowered = raw.lower()
    if "thesis title" in lowered:
        return raw.split(":", 1)[-1].strip().strip('"')
    return raw.strip().strip('"')

# Page UI
st.set_page_config(page_title="Parse Thesis Table", layout="wide")
st.title("Parse thesis chapter table → template")
st.markdown("Load a markdown table and generate the dropdown-based template.")

md_path = "new_app/pages/system/working/01.md"
md_text = load_text(md_path)
if not md_text:
    st.error(f"Could not read {md_path}")
    st.stop()

rows = parse_markdown_table(md_text)
if not rows:
    st.error("No markdown table rows found in file.")
    st.code(md_text)
    st.stop()

# load metadata if available
meta_path = "new_app/pages/documentation_succesful/template_metadata.json"
metadata = load_metadata(meta_path)
thesis_title = extract_thesis_title(metadata.get("title", DEFAULT_TEMPLATE_METADATA["title"]))

# allow filtering by Chapter (optional)
chapters = sorted({r.get("Chapter", "").strip() for r in rows if r.get("Chapter")})
chap_choice = st.selectbox("Filter by Chapter (optional)", options=["All"] + chapters, index=0)
filtered = [r for r in rows if chap_choice == "All" or r.get("Chapter", "").strip() == chap_choice]

# selection dropdown: show Section + Title
options = [
    (i, f"{r.get('Chapter','').strip()} {r.get('Section','').strip()} — {r.get('Title','').strip()}")
    for i, r in enumerate(filtered)
]
sel_index = st.selectbox("Select section to generate template", options=[lbl for _, lbl in options])
selected_row = filtered[[i for i, lbl in options if lbl == sel_index][0]]

# Build template with placeholders filled from selected row + metadata
context = selected_row.get("Context", "").strip()
section_title = selected_row.get("Title", "").strip()
objective = selected_row.get("Objective", "").strip()
writing_requirements = selected_row.get("Writing Requirements", "").strip()

template = f"""You are an academic researcher writing a Master's thesis.

Thesis Title:
\"{thesis_title}\"

---

## THESIS CONTEXT

{context}
---

## PREVIOUSLY WRITTEN SECTION

This is the first section of the thesis.

---

## SECTION TO WRITE

Section Title:
{section_title}
---

## SECTION OBJECTIVE
{objective}
---

## WRITING REQUIREMENTS
{writing_requirements}
---

## OUTPUT FORMAT

Return the output as LaTeX-ready text using:

\\subsection{{{section_title}}}

Do not include explanations outside the LaTeX text.
"""

st.markdown("### Generated template")
st.code(template, language="text")
st.markdown("You can copy the template from the code box above.")
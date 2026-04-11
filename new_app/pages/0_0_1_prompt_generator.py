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

working_dir = Path("new_app/pages/system/working")
md_files = sorted(list(working_dir.glob("*.md")))

if not md_files:
    st.error(f"No .md files found in {working_dir}")
    st.stop()

selected_file = st.selectbox(
    "Select Markdown File", 
    options=md_files, 
    format_func=lambda x: x.name
)

md_text = load_text(str(selected_file))
if not md_text:
    st.error(f"Could not read {selected_file}")
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

# NEW: load and edit thesis context (if stored) or leave blank
default_context = metadata.get("context", "")
edited_context = st.text_area(
    "Thesis context (will also be included in LaTeX table)",
    value=default_context,
    height=120,
)
col_save_title, col_save_context = st.columns([1, 1])
with col_save_title:
    if st.button("Save thesis title to metadata"):
        try:
            metadata["title"] = f'Thesis Title: \"{thesis_title}\"'
            Path(meta_path).write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            st.success("Thesis title saved to template metadata.")
        except Exception as e:
            st.error(f"Failed to save metadata: {e}")
with col_save_context:
    if st.button("Save thesis context to metadata"):
        try:
            metadata["context"] = edited_context
            Path(meta_path).write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            st.success("Thesis context saved to template metadata.")
        except Exception as e:
            st.error(f"Failed to save metadata: {e}")

# use the edited title/context in the generated template
thesis_title = st.text_input("Thesis title", value=thesis_title)
thesis_context_global = edited_context

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

# NEW: multi-select for LaTeX table creation
multi_labels = [lbl for _, lbl in options]
selected_multi = st.multiselect(
    "Select sections to include in LaTeX table",
    options=multi_labels,
)

# Build template with placeholders filled from selected row + metadata
context = selected_row.get("Context", "").strip() or thesis_context_global.strip()
section_title = selected_row.get("Title", "").strip()
objective = selected_row.get("Objective", "").strip()
writing_requirements = selected_row.get("Writing Requirements", "").strip()

template = f"""You are an academic researcher writing a Master's thesis.

Thesis Title:
\"{thesis_title}\"

## THESIS CONTEXT: {context}

## PREVIOUSLY WRITTEN SECTION

This is the first section of the thesis.

---

## SECTION TO WRITE

Section Title: {section_title}

## SECTION OBJECTIVE: {objective}

## WRITING REQUIREMENTS: {writing_requirements}

## OUTPUT FORMAT

Return the output as LaTeX-ready text using:

\\subsection{{{section_title}}}

Do not include explanations outside the LaTeX text.
"""

st.markdown("### Generated template")
st.code(template, language="text")
st.markdown("You can copy the template from the code box above.")

# New: options to show the generated content as a table
display_option = st.radio(
    "Display template as",
    options=["Text (default)", "Streamlit table", "Markdown table"],
    index=0,
)

if display_option != "Text (default)":
    table_rows = [
        {"Field": "Thesis Title", "Content": thesis_title},
        {"Field": "Thesis Context", "Content": context},
        {"Field": "Section Title", "Content": section_title},
        {"Field": "Section Objective", "Content": objective},
        {"Field": "Writing Requirements", "Content": writing_requirements},
        {"Field": "Output Format (snippet)", "Content": f"\\subsection{{{section_title}}}"},
        {"Field": "Full Template", "Content": template},
    ]

    if display_option == "Streamlit table":
        st.table(table_rows)
    else:
        # build a markdown table; escape pipes in content and preserve newlines as <br>
        md = "| Field | Content |\n|---|---|\n"
        for r in table_rows:
            content = r["Content"].replace("|", "\\|").replace("\n", "<br>")
            md += f"| {r['Field']} | {content} |\n"
        st.markdown(md, unsafe_allow_html=True)

# NEW: LaTeX table generation for multi-selected rows
st.markdown("### LaTeX table for selected sections")

if selected_multi:
    # map label -> row
    label_to_row = {
        lbl: filtered[idx]
        for idx, lbl in options
    }
    selected_rows_for_table = [label_to_row[lbl] for lbl in selected_multi if lbl in label_to_row]

    # Define which columns you want in the LaTeX table
    # ADDED: 'Thesis Context' column (uses global thesis_context_global)
    table_columns = ["Chapter", "Section", "Title", "Objective", "Thesis Context"]

    # Build LaTeX tabular environment
    col_spec = " | ".join(["l"] * len(table_columns))
    header_line = " & ".join(table_columns) + " \\\\ \\hline\n"

    body_lines = ""
    for r in selected_rows_for_table:
        cells = []
        for c in table_columns:
            if c == "Thesis Context":
                val = thesis_context_global or default_context or ""
            else:
                val = (r.get(c, "") or "")
            val = val.replace("\n", " ")
            # simple escaping of LaTeX special chars
            val = (
                val.replace("\\", "\\textbackslash{}")
                   .replace("&", "\\&")
                   .replace("%", "\\%")
                   .replace("$", "\\$")
                   .replace("#", "\\#")
                   .replace("_", "\\_")
                   .replace("{", "\\{")
                   .replace("}", "\\}")
            )
            cells.append(val)
        body_lines += " & ".join(cells) + " \\\\ \\hline\n"

    latex_table = (
        "\\begin{table}[ht]\n"
        "\\centering\n"
        f"\\begin{{tabular}}{{{col_spec}}}\n"
        "\\hline\n"
        f"{header_line}"
        f"{body_lines}"
        "\\end{tabular}\n"
        "\\caption{Sections overview}\n"
        "\\label{tab:sections_overview}\n"
        "\\end{table}\n"
    )

    st.markdown("Copy-paste the LaTeX table below into your thesis:")
    st.code(latex_table, language="latex")
else:
    st.info("Select one or more sections above to generate a LaTeX table.")
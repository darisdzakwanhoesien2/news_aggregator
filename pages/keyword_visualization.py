import streamlit as st
import json
from pathlib import Path
import pandas as pd
from _page_descriptions import render_page_description

# =========================================================
# CONFIG
# =========================================================

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# Automatically discover keyword JSON files
KEYWORD_FILES = sorted(DATA_DIR.glob("esg_keywords*.json"))

# =========================================================
# LOADERS
# =========================================================

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_all_keyword_files(files):
    datasets = {}
    for path in files:
        datasets[path.name] = load_json(path)
    return datasets


# =========================================================
# NORMALIZATION
# =========================================================

def normalize_datasets(datasets):
    """
    Convert all JSON keyword mappings into a flat table:
    file | company_code | keyword
    """
    rows = []

    for filename, data in datasets.items():
        for company, keywords in data.items():
            for kw in keywords:
                rows.append({
                    "file": filename,
                    "company_code": company,
                    "keyword": kw.strip().lower()
                })

    return pd.DataFrame(rows)


# =========================================================
# STREAMLIT UI
# =========================================================

st.set_page_config(layout="wide")
st.title("📊 ESG Keyword Mapping Dashboard")
render_page_description(__file__)
st.caption("Visualize and compare keyword mappings across multiple JSON versions")

# =========================================================
# FILE SELECTION
# =========================================================

if not KEYWORD_FILES:
    st.error("No keyword files found in /data (expected esg_keywords*.json)")
    st.stop()

with st.sidebar:
    st.header("📂 Keyword JSON Files")

    selected_files = st.multiselect(
        "Select keyword files",
        options=[p.name for p in KEYWORD_FILES],
        default=[KEYWORD_FILES[0].name]
    )

    if not selected_files:
        st.warning("Select at least one file.")
        st.stop()

    selected_paths = [DATA_DIR / f for f in selected_files]

# =========================================================
# LOAD DATA
# =========================================================

datasets = load_all_keyword_files(selected_paths)
df = normalize_datasets(datasets)

st.success(f"Loaded {len(selected_files)} files | {len(df)} total keyword rows")

# =========================================================
# FILTERS
# =========================================================

with st.sidebar:
    st.header("🔎 Filters")

    companies = sorted(df["company_code"].unique())
    selected_companies = st.multiselect(
        "Filter companies",
        companies,
        default=companies
    )

    keywords_search = st.text_input("Keyword contains")

filtered_df = df[df["company_code"].isin(selected_companies)]

if keywords_search:
    filtered_df = filtered_df[
        filtered_df["keyword"].str.contains(keywords_search.lower(), na=False)
    ]

# =========================================================
# METRICS
# =========================================================

col1, col2, col3, col4 = st.columns(4)

col1.metric("📁 Files Loaded", len(selected_files))
col2.metric("🏢 Companies", filtered_df["company_code"].nunique())
col3.metric("🔑 Total Keywords", len(filtered_df))
col4.metric("🧬 Unique Keywords", filtered_df["keyword"].nunique())

# =========================================================
# TABLE VIEW
# =========================================================

st.subheader("📋 Keyword Mapping Table")
st.dataframe(filtered_df, use_container_width=True)

# =========================================================
# AGGREGATIONS
# =========================================================

st.divider()
st.subheader("📈 Analytics")

# ---------------- Keywords per Company ----------------

st.markdown("### 🔹 Keywords per Company")

kw_per_company = (
    filtered_df.groupby("company_code")["keyword"]
    .nunique()
    .reset_index(name="keyword_count")
    .sort_values("keyword_count", ascending=False)
)

st.dataframe(kw_per_company, use_container_width=True)
st.bar_chart(kw_per_company.set_index("company_code"))

# ---------------- Keywords per File ----------------

st.markdown("### 🔹 Keywords per JSON File")

kw_per_file = (
    filtered_df.groupby("file")["keyword"]
    .nunique()
    .reset_index(name="keyword_count")
)

st.dataframe(kw_per_file, use_container_width=True)
st.bar_chart(kw_per_file.set_index("file"))

# ---------------- Overlap Analysis ----------------

if len(selected_files) > 1:
    st.markdown("### 🔹 Keyword Overlap Between Files")

    pivot = filtered_df.pivot_table(
        index="keyword",
        columns="file",
        values="company_code",
        aggfunc="count",
        fill_value=0
    )

    pivot["files_present"] = (pivot > 0).sum(axis=1)

    overlap_stats = (
        pivot["files_present"]
        .value_counts()
        .sort_index()
        .reset_index()
        .rename(columns={
            "index": "files_present",
            "files_present": "keyword_count"
        })
    )

    st.dataframe(overlap_stats, use_container_width=True)
    st.bar_chart(overlap_stats.set_index("files_present"))

# =========================================================
# COMPANY COMPARISON
# =========================================================

st.divider()
st.subheader("🏢 Company Keyword Comparison")

selected_company = st.selectbox(
    "Select company",
    sorted(filtered_df["company_code"].unique())
)

company_view = filtered_df[
    filtered_df["company_code"] == selected_company
]

pivot_company = company_view.pivot_table(
    index="keyword",
    columns="file",
    values="company_code",
    aggfunc="count",
    fill_value=0
)

st.dataframe(pivot_company, use_container_width=True)

# =========================================================
# EXPORT
# =========================================================

st.divider()
st.subheader("⬇️ Export")

csv_data = filtered_df.to_csv(index=False)
st.download_button(
    "Download Filtered CSV",
    csv_data,
    file_name="esg_keyword_mapping.csv",
    mime="text/csv"
)

json_data = filtered_df.to_dict(orient="records")
st.download_button(
    "Download Filtered JSON",
    json.dumps(json_data, indent=2),
    file_name="esg_keyword_mapping.json",
    mime="application/json"
)

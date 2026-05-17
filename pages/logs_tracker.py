import streamlit as st
import json
import pandas as pd
from pathlib import Path
from _page_descriptions import render_page_description

# =============================
# PAGE CONFIG
# =============================
st.set_page_config(
    page_title="📊 Run Log Analyzer",
    layout="wide"
)

st.title("📊 Run Log Analyzer")
render_page_description(__file__)
st.caption("Analyze query runs, fetched results, and batch saves")

# =============================
# PATHS
# =============================
BASE_DIR = Path(__file__).parents[1]
LOG_PATH = BASE_DIR / "logs" / "scraper_runs.jsonl"

# =============================
# LOAD LOG FILE
# =============================
@st.cache_data
def load_logs(path: Path):
    if not path.exists():
        st.error(f"❌ Log file not found: {path}")
        st.stop()

    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception as e:
                st.warning(f"⚠️ Skipped invalid line: {e}")

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    return df


df = load_logs(LOG_PATH)

if df.empty:
    st.warning("No logs loaded.")
    st.stop()

# =============================
# SIDEBAR FILTERS
# =============================
st.sidebar.header("🎛 Filters")

run_ids = sorted(df["run_id"].dropna().unique())
selected_run = st.sidebar.selectbox("Run ID", run_ids)

filtered = df[df["run_id"] == selected_run].copy()

companies = sorted(
    filtered.get("company_code", pd.Series()).dropna().unique()
)

selected_company = st.sidebar.multiselect(
    "Company",
    options=companies,
    default=companies
)

if selected_company:
    filtered = filtered[
        (filtered["company_code"].isin(selected_company)) |
        (filtered["company_code"].isna())
    ]

# =============================
# METRICS
# =============================
col1, col2, col3, col4, col5 = st.columns(5)

total_queries = len(filtered[filtered["event"] == "query_fetched"])
total_fetched = filtered.get("fetched", pd.Series()).fillna(0).sum()

total_batches = len(filtered[filtered["event"] == "batch_saved"])
total_saved = filtered.get("saved", pd.Series()).fillna(0).sum()

active_companies = filtered.get("company_code", pd.Series()).dropna().nunique()

col1.metric("🔎 Queries", total_queries)
col2.metric("📦 Total Fetched", int(total_fetched))
col3.metric("💾 Batches Saved", total_batches)
col4.metric("✅ Records Saved", int(total_saved))
col5.metric("🏢 Companies", int(active_companies))

st.divider()

# =============================
# COMPANY SUMMARY
# =============================
st.subheader("🏢 Company Performance Summary")

query_df = filtered[filtered["event"] == "query_fetched"].copy()

if not query_df.empty:
    company_summary = (
        query_df
        .groupby("company_code", dropna=True)
        .agg(
            queries=("keyword", "count"),
            total_fetched=("fetched", "sum"),
            avg_fetched=("fetched", "mean"),
            max_fetched=("fetched", "max"),
        )
        .reset_index()
        .sort_values("total_fetched", ascending=False)
    )

    st.dataframe(company_summary, use_container_width=True)

else:
    st.info("No query data available.")

st.divider()

# =============================
# KEYWORD PERFORMANCE
# =============================
st.subheader("🔑 Keyword Yield Mapping")

if not query_df.empty:
    keyword_table = (
        query_df
        .sort_values("fetched", ascending=False)
        [["company_code", "keyword", "fetched", "timestamp"]]
    )

    st.dataframe(keyword_table, use_container_width=True)

st.divider()

# =============================
# TIMELINE VIEW
# =============================
st.subheader("⏱ Event Timeline")

timeline = filtered.sort_values("timestamp")

timeline_cols = [
    "timestamp",
    "event",
    "company_code",
    "keyword",
    "fetched",
    "batch_size",
    "saved",
]

existing_cols = [c for c in timeline_cols if c in timeline.columns]

st.dataframe(
    timeline[existing_cols],
    use_container_width=True,
    height=400
)

st.divider()

# =============================
# RAW LOG VIEW
# =============================
with st.expander("📄 Raw Log Data"):
    st.dataframe(filtered.sort_values("timestamp"), use_container_width=True)

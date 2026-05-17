import streamlit as st
import pandas as pd
import json
from pathlib import Path
from _page_descriptions import render_page_description

# =========================
# PAGE CONFIG
# =========================

st.set_page_config(
    page_title="📰 News Dataset Distribution",
    layout="wide"
)

st.title("📰 News Dataset — Distribution Dashboard")
render_page_description(__file__)
st.caption("Visual analytics for news_dataset.json")

# =========================
# PATHS
# =========================

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_PATH = BASE_DIR / "data" / "news_dataset_new.json"

if not DATA_PATH.exists():
    st.error(f"❌ File not found: {DATA_PATH}")
    st.stop()

# =========================
# LOAD DATA
# =========================

with open(DATA_PATH, encoding="utf-8") as f:
    raw_data = json.load(f)

df = pd.DataFrame(raw_data)

# =========================
# PREPROCESSING
# =========================

# Parse published datetime
df["published_dt"] = pd.to_datetime(
    df["published"], errors="coerce", utc=True
)

df["date"] = df["published_dt"].dt.date
df["year"] = df["published_dt"].dt.year
df["month"] = df["published_dt"].dt.to_period("M").astype(str)

# =========================
# SIDEBAR FILTERS
# =========================

st.sidebar.header("🔎 Filters")

selected_sources = st.sidebar.multiselect(
    "Source",
    sorted(df["source"].dropna().unique()),
    default=sorted(df["source"].dropna().unique())
)

selected_status = st.sidebar.multiselect(
    "Status",
    sorted(df["status"].dropna().unique()),
    default=sorted(df["status"].dropna().unique())
)

filtered_df = df[
    (df["source"].isin(selected_sources)) &
    (df["status"].isin(selected_status))
]

# =========================
# METRICS
# =========================

col1, col2, col3, col4 = st.columns(4)

col1.metric("📰 Total Articles", len(filtered_df))
col2.metric("🏷 Unique Sources", filtered_df["source"].nunique())
col3.metric("🔍 Unique Queries", filtered_df["query"].nunique())
col4.metric("📅 Date Range",
             f"{filtered_df['date'].min()} → {filtered_df['date'].max()}")

st.divider()

# =========================
# DATA PREVIEW
# =========================

with st.expander("📄 Preview Dataset"):
    st.dataframe(filtered_df, use_container_width=True)

# =========================
# CHART HELPERS
# =========================

def plot_bar(series, title, xlabel, ylabel):
    chart_df = series.rename(ylabel).to_frame()
    st.caption(title)
    st.bar_chart(chart_df, use_container_width=True)


# =========================
# VISUALIZATIONS
# =========================

colA, colB = st.columns(2)

# ---- Articles over time ----
with colA:
    st.subheader("📈 Articles Over Time (by Date)")
    time_counts = (
        filtered_df.groupby("date")
        .size()
        .sort_index()
    )
    st.line_chart(
        time_counts.rename("Number of Articles").to_frame(),
        use_container_width=True,
    )

# ---- Source distribution ----
with colB:
    st.subheader("🏢 Articles by Source")
    source_counts = filtered_df["source"].value_counts()
    plot_bar(
        source_counts,
        "Articles by Source",
        "Source",
        "Count"
    )

st.divider()

colC, colD = st.columns(2)

# ---- Query distribution ----
with colC:
    st.subheader("🔍 Articles by Query")
    query_counts = filtered_df["query"].value_counts()
    plot_bar(
        query_counts,
        "Articles by Query",
        "Query",
        "Count"
    )

# ---- Status distribution ----
with colD:
    st.subheader("✅ Articles by Status")
    status_counts = filtered_df["status"].value_counts()
    plot_bar(
        status_counts,
        "Articles by Status",
        "Status",
        "Count"
    )

st.divider()

# ---- Monthly trend ----
st.subheader("📆 Monthly Publishing Trend")

monthly_counts = (
    filtered_df.groupby("month")
    .size()
    .sort_index()
)
st.line_chart(
    monthly_counts.rename("Articles").to_frame(),
    use_container_width=True,
)

st.divider()

# =========================
# TOP ARTICLES TABLE
# =========================

st.subheader("🔥 Latest Articles")

latest_df = (
    filtered_df
    .sort_values("published_dt", ascending=False)
    [["published", "title", "source", "query", "status", "link"]]
    .head(20)
)

st.dataframe(latest_df, use_container_width=True)

st.success("✅ Dashboard loaded successfully.")

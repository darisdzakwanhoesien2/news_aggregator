import streamlit as st
import pandas as pd
import json
from pathlib import Path
import matplotlib.pyplot as plt
import time

# =========================
# PAGE CONFIG
# =========================
st.set_page_config(page_title="📰 News Dataset Visualizer", layout="wide")
st.title("📰 News Dataset Visualizer")
st.caption("Auto-refresh dashboard for news_dataset.json")

# =========================
# PATHS
# =========================
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_PATH = BASE_DIR / "data" / "news_dataset.json"

# =========================
# FILE CHANGE TRACKING
# =========================
def get_file_signature(path: Path):
    """
    Returns (mtime, size) to detect file changes reliably.
    """
    if not path.exists():
        return None
    stat = path.stat()
    return (stat.st_mtime, stat.st_size)


# Session state
if "file_sig" not in st.session_state:
    st.session_state.file_sig = None


@st.cache_data(show_spinner=False)
def load_data_cached(file_sig):
    """
    Cache invalidates automatically when file_sig changes.
    """
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    df = pd.DataFrame(raw)
    df["published"] = pd.to_datetime(df["published"], errors="coerce")
    return df


def load_data():
    sig = get_file_signature(DATA_PATH)

    if sig is None:
        return pd.DataFrame()

    # Invalidate cache if file changed
    if sig != st.session_state.file_sig:
        st.cache_data.clear()
        st.session_state.file_sig = sig

    return load_data_cached(sig)


# =========================
# REFRESH CONTROLS
# =========================
col_r1, col_r2, col_r3, col_r4 = st.columns([1, 1, 2, 2])

with col_r1:
    if st.button("🔄 Refresh Now"):
        st.cache_data.clear()
        st.experimental_rerun()

with col_r2:
    auto_refresh = st.toggle("⏱ Auto Refresh", value=False)

with col_r3:
    refresh_interval = st.slider(
        "Refresh interval (seconds)",
        min_value=5,
        max_value=120,
        value=30,
        step=5,
        disabled=not auto_refresh,
    )

with col_r4:
    sig = get_file_signature(DATA_PATH)
    if sig:
        last_update = pd.to_datetime(sig[0], unit="s")
        st.caption(f"📁 Last update: {last_update}")
    else:
        st.caption("📁 Waiting for data file...")

# =========================
# LOAD DATA
# =========================
df = load_data()

# Auto refresh loop
if auto_refresh:
    time.sleep(refresh_interval)
    st.experimental_rerun()

# Safety guard
if df.empty:
    st.info("⏳ Waiting for news_dataset.json to appear or receive data...")
    st.stop()

st.success(f"✅ Loaded {len(df)} news articles")

# =========================
# SIDEBAR FILTERS
# =========================
st.sidebar.header("🎛 Filters")

company_codes = sorted(df["company_code"].dropna().unique())
selected_companies = st.sidebar.multiselect(
    "Select Company Code(s)",
    options=company_codes,
    default=company_codes
)

filtered_df = df[df["company_code"].isin(selected_companies)]

# =========================
# METRICS
# =========================
col1, col2, col3 = st.columns(3)
col1.metric("Total Articles", len(filtered_df))
col2.metric("Companies", filtered_df["company_code"].nunique())
col3.metric("Sources", filtered_df["source"].nunique())

st.divider()

# =========================
# DATA PREVIEW
# =========================
with st.expander("🔍 Preview Dataset"):
    st.dataframe(
        filtered_df[
            [
                "company_code",
                "company_name",
                "title",
                "source",
                "published",
                "esg_score",
            ]
        ]
        .sort_values("published", ascending=False),
        use_container_width=True,
    )

# =========================
# CHART 1 — Articles per Company
# =========================
st.subheader("📊 Articles per Company")

company_counts = (
    filtered_df.groupby("company_code")
    .size()
    .sort_values(ascending=False)
)

fig1, ax1 = plt.subplots()
company_counts.plot(kind="bar", ax=ax1)
ax1.set_xlabel("Company Code")
ax1.set_ylabel("Number of Articles")
ax1.set_title("News Volume by Company")
st.pyplot(fig1)

# =========================
# CHART 2 — ESG Score Distribution
# =========================
st.subheader("🌱 ESG Score Distribution")

fig2, ax2 = plt.subplots()
filtered_df["esg_score"].dropna().plot(kind="hist", bins=20, ax=ax2)
ax2.set_xlabel("ESG Score")
ax2.set_ylabel("Frequency")
ax2.set_title("Distribution of ESG Scores")
st.pyplot(fig2)

# =========================
# CHART 3 — Articles Over Time
# =========================
st.subheader("📅 Articles Over Time")

time_counts = (
    filtered_df
    .dropna(subset=["published"])
    .set_index("published")
    .resample("W")
    .size()
)

fig3, ax3 = plt.subplots()
time_counts.plot(ax=ax3)
ax3.set_xlabel("Week")
ax3.set_ylabel("Number of Articles")
ax3.set_title("News Volume Over Time")
st.pyplot(fig3)

# =========================
# CHART 4 — Source Distribution
# =========================
st.subheader("🗞 Source Distribution")

source_counts = (
    filtered_df["source"]
    .value_counts()
    .head(15)
)

fig4, ax4 = plt.subplots()
source_counts.plot(kind="barh", ax=ax4)
ax4.set_xlabel("Articles")
ax4.set_ylabel("Source")
ax4.set_title("Top News Sources")
st.pyplot(fig4)

# =========================
# COMPANY SUMMARY TABLE
# =========================
st.subheader("🏢 Company Summary")

summary_df = (
    filtered_df
    .groupby(["company_code", "company_name"])
    .agg(
        articles=("title", "count"),
        avg_esg=("esg_score", "mean"),
        sources=("source", "nunique"),
        first_article=("published", "min"),
        latest_article=("published", "max"),
    )
    .reset_index()
    .sort_values("articles", ascending=False)
)

st.dataframe(summary_df, use_container_width=True)

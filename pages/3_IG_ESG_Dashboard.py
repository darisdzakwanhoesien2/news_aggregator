import streamlit as st
import pandas as pd
import json
from pathlib import Path
from _page_descriptions import render_page_description

# ======================================
# Config
# ======================================
DATA_DIR = Path("data/posts")

st.set_page_config(
    page_title="📊 ESG Instagram Dashboard",
    layout="wide"
)

st.title("📊 ESG Instagram Monitoring Dashboard")
render_page_description(__file__)
st.markdown("""
This dashboard visualizes **scraped Instagram datasets**  
grouped by **company (username)** and **scrape date**.
""")

# ======================================
# Helpers
# ======================================
def list_datasets():
    records = []

    for file in DATA_DIR.glob("*.json"):
        try:
            username, date = file.stem.rsplit("_", 1)
            records.append({
                "company": username,
                "scrape_date": date,
                "file": file
            })
        except ValueError:
            continue

    return pd.DataFrame(records)


def load_posts(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

# ======================================
# Load dataset index
# ======================================
index_df = list_datasets()

if index_df.empty:
    st.warning("No scraped datasets found in data/posts/")
    st.stop()

# ======================================
# SECTION 1 — DATASET OVERVIEW
# ======================================
st.subheader("📁 Available Scrape Batches")

summary_rows = []

for _, row in index_df.iterrows():
    posts = load_posts(row["file"])
    summary_rows.append({
        "Company": row["company"],
        "Scrape Date": row["scrape_date"],
        "Posts Count": len(posts)
    })

summary_df = pd.DataFrame(summary_rows)

st.dataframe(
    summary_df.sort_values(["Company", "Scrape Date"], ascending=[True, False]),
    use_container_width=True
)

# ======================================
# SECTION 2 — FILTERS
# ======================================
st.subheader("🎯 Select Company & Scrape Date")

col1, col2 = st.columns(2)

with col1:
    selected_company = st.selectbox(
        "Company / IG Username",
        sorted(index_df["company"].unique())
    )

with col2:
    available_dates = (
        index_df[index_df["company"] == selected_company]
        .sort_values("scrape_date", ascending=False)["scrape_date"]
        .tolist()
    )

    selected_date = st.selectbox(
        "Scrape Date",
        available_dates
    )

selected_file = index_df[
    (index_df["company"] == selected_company) &
    (index_df["scrape_date"] == selected_date)
]["file"].iloc[0]

# ======================================
# SECTION 3 — POSTS VIEW
# ======================================
st.subheader(f"📄 Posts — {selected_company} ({selected_date})")

posts = load_posts(selected_file)
df = pd.DataFrame(posts)

if df.empty:
    st.info("No posts found.")
    st.stop()

# Normalize timestamps
df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
df["scraped_at"] = pd.to_datetime(df["scraped_at"], errors="coerce")

# Engagement metrics
metrics_col1, metrics_col2, metrics_col3 = st.columns(3)

metrics_col1.metric("Total Posts", len(df))
metrics_col2.metric("Avg Likes", int(df["likes"].mean()))
metrics_col3.metric("Avg Comments", int(df["comments"].mean()))

# ======================================
# Post Table
# ======================================
st.markdown("### 🗂 Post Details")

display_cols = [
    "timestamp",
    "likes",
    "comments",
    "caption",
    "url"
]

st.dataframe(
    df[display_cols]
    .sort_values("timestamp", ascending=False),
    use_container_width=True,
    column_config={
        "caption": st.column_config.TextColumn(
            width="large"
        ),
        "url": st.column_config.LinkColumn(
            "Instagram Post"
        )
    }
)

# ======================================
# Download
# ======================================
st.download_button(
    "⬇️ Download Filtered Dataset (JSON)",
    data=df.to_json(orient="records", indent=2, date_format="iso"),
    file_name=f"{selected_company}_{selected_date}_filtered.json"
)

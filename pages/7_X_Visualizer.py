import streamlit as st
import pandas as pd
import json
from pathlib import Path

# =====================================================
# Config
# =====================================================
DATA_DIR = Path("data/x")

st.set_page_config(
    page_title="🐦 X (Twitter) ESG Visualizer",
    layout="wide"
)

st.title("🐦 X (Twitter) ESG Visualization")
st.markdown("""
Analyze **X posts** by **NGOs, companies, and media**.  
This view supports **historical scraping**, **incremental updates**, and **ESG analysis**.
""")

# =====================================================
# Helpers
# =====================================================
def list_datasets():
    rows = []

    for file in DATA_DIR.glob("*.json"):
        try:
            username, date = file.stem.rsplit("_", 1)
            rows.append({
                "username": username,
                "scrape_date": date,
                "file": file
            })
        except ValueError:
            continue

    return pd.DataFrame(rows)


def load_posts(file_path):
    with open(file_path, encoding="utf-8") as f:
        return json.load(f)

# =====================================================
# Dataset index
# =====================================================
index_df = list_datasets()

if index_df.empty:
    st.warning("No X datasets found in data/x/")
    st.stop()

# =====================================================
# SECTION 1 — DATASET OVERVIEW
# =====================================================
st.subheader("📁 Available X Scrape Batches")

summary = []

for _, row in index_df.iterrows():
    posts = load_posts(row["file"])
    summary.append({
        "Username": row["username"],
        "Scrape Date": row["scrape_date"],
        "Posts Count": len(posts)
    })

summary_df = pd.DataFrame(summary)

st.dataframe(
    summary_df.sort_values(["Username", "Scrape Date"], ascending=[True, False]),
    use_container_width=True
)

# =====================================================
# SECTION 2 — FILTERS
# =====================================================
st.subheader("🎯 Select Account & Scrape Date")

col1, col2 = st.columns(2)

with col1:
    selected_user = st.selectbox(
        "X Username",
        sorted(index_df["username"].unique())
    )

with col2:
    dates = (
        index_df[index_df["username"] == selected_user]
        .sort_values("scrape_date", ascending=False)["scrape_date"]
        .tolist()
    )

    selected_date = st.selectbox("Scrape Date", dates)

selected_file = index_df[
    (index_df["username"] == selected_user) &
    (index_df["scrape_date"] == selected_date)
]["file"].iloc[0]

posts = load_posts(selected_file)
df = pd.DataFrame(posts)

# =====================================================
# Normalize columns
# =====================================================
for col in ["likes", "comments", "shares", "views"]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
df["scraped_at"] = pd.to_datetime(df["scraped_at"], errors="coerce")

# =====================================================
# SECTION 3 — ENGAGEMENT TIME SERIES
# =====================================================
st.subheader("📈 Engagement Over Time")

# Use scraped_at when timestamp is missing (common for X scraping)
df["time_axis"] = df["timestamp"].fillna(df["scraped_at"])

ts_cols = st.columns(3)

with ts_cols[0]:
    if df["likes"].notna().any():
        st.line_chart(df.set_index("time_axis")[["likes"]], height=220)
    else:
        st.info("Likes data not available")

with ts_cols[1]:
    if df["comments"].notna().any():
        st.line_chart(df.set_index("time_axis")[["comments"]], height=220)
    else:
        st.info("Comments data not available")

with ts_cols[2]:
    if df["shares"].notna().any():
        st.line_chart(df.set_index("time_axis")[["shares"]], height=220)
    else:
        st.info("Shares data not available")

# =====================================================
# SECTION 4 — POST SELECTOR
# =====================================================
st.subheader("📝 Select Post")

def post_label(row):
    text = row["content"].split("\n")[0][:80]
    return f"{row['post_id']} | {text}..."

selected_idx = st.selectbox(
    "Post",
    df.index,
    format_func=lambda i: post_label(df.loc[i])
)

post = df.loc[selected_idx]

# =====================================================
# SECTION 5 — POST DETAILS
# =====================================================
st.subheader("📄 Post Details")

m1, m2, m3, m4 = st.columns(4)

m1.metric("Likes", int(post["likes"]) if pd.notna(post["likes"]) else "—")
m2.metric("Comments", int(post["comments"]) if pd.notna(post["comments"]) else "—")
m3.metric("Shares", int(post["shares"]) if pd.notna(post["shares"]) else "—")
m4.metric("Source", post.get("source_type", "—"))

st.markdown("### Content")
st.text(post["content"])

st.link_button("🔗 Open on X", post["url"])

# =====================================================
# Download
# =====================================================
st.download_button(
    "⬇️ Download Filtered Dataset",
    df.to_json(orient="records", indent=2, date_format="iso"),
    file_name=f"x_{selected_user}_{selected_date}_filtered.json"
)

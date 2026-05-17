import streamlit as st
import pandas as pd
from utils.instagram_oembed import fetch_oembed
from utils.media_snapshot import render_snapshot
from utils.post_loader import load_all_posts

# =====================================================
# Page config
# =====================================================
st.set_page_config(
    page_title="📸 Instagram Post Visualizer",
    layout="wide"
)

st.title("📸 Instagram Post Visualizer")
st.markdown("""
Explore Instagram posts by **company**, analyze **engagement over time**,  
and visually verify posts using **live embed + archived snapshots**.
""")

# =====================================================
# Load data
# =====================================================
posts = load_all_posts()

if not posts:
    st.warning("No posts found in data/posts/")
    st.stop()

df = pd.DataFrame(posts)

# Normalize datetime fields
df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
df["scraped_at"] = pd.to_datetime(df["scraped_at"], errors="coerce")

# Sort chronologically
df = df.sort_values("timestamp")

# =====================================================
# SECTION 1 — TIME SERIES (TOP)
# =====================================================
st.subheader("📈 Engagement Over Time")

ts_col1, ts_col2 = st.columns(2)

with ts_col1:
    st.line_chart(
        df.set_index("timestamp")[["likes"]],
        height=250
    )

with ts_col2:
    st.line_chart(
        df.set_index("timestamp")[["comments"]],
        height=250
    )

# =====================================================
# SECTION 2 — FILTERS
# =====================================================
st.subheader("🎯 Select Company & Post")

filter_col1, filter_col2 = st.columns(2)

with filter_col1:
    selected_company = st.selectbox(
        "Company / Instagram Username",
        sorted(df["username"].unique())
    )

company_df = df[df["username"] == selected_company]

with filter_col2:
    selected_shortcode = st.selectbox(
        "Post",
        company_df.sort_values("timestamp", ascending=False)["shortcode"],
        format_func=lambda sc: f"{sc} | {company_df[company_df['shortcode'] == sc]['timestamp'].iloc[0].date()}"
    )

selected_post = company_df[
    company_df["shortcode"] == selected_shortcode
].iloc[0].to_dict()

# =====================================================
# SECTION 3 — POST METRICS
# =====================================================
st.subheader("📊 Selected Post Metrics")

m1, m2, m3 = st.columns(3)

m1.metric("Likes", selected_post["likes"])
m2.metric("Comments", selected_post["comments"])
m3.metric("Post Date", selected_post["timestamp"].date().isoformat())

# =====================================================
# SECTION 4 — VISUAL REPRESENTATION
# =====================================================
st.subheader("🅰️ Live Instagram Preview")

try:
    embed = fetch_oembed(selected_post["url"])
    st.components.v1.html(
        embed["html"],
        height=700,
        scrolling=True
    )
    st.caption("Live Instagram embed (official)")
except Exception:
    st.warning("Live preview unavailable. Showing archived snapshot instead.")
    render_snapshot(selected_post)

# =====================================================
# SECTION 5 — ARCHIVED SNAPSHOT (ALWAYS SHOWN)
# =====================================================
st.divider()
render_snapshot(selected_post)

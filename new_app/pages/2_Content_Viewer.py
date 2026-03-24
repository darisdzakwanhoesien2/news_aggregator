# pages/Content_Viewer.py

import streamlit as st
import json
import pandas as pd
import os

st.set_page_config(page_title="News Content Viewer", layout="wide")
st.title("📋 News Content Viewer & URL Inspector")

# -----------------------------
# Load Scraped Content
# -----------------------------
SCRAPED_FILE = "data/news_content.json"

@st.cache_data
def load_scraped():
    if os.path.exists(SCRAPED_FILE):
        with open(SCRAPED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

scraped_data = load_scraped()

if not scraped_data:
    st.error("❌ No scraped data found. Please run the News Extractor first.")
    st.stop()

# -----------------------------
# Build Summary DataFrame
# -----------------------------
rows = []
for link, data in scraped_data.items():
    resolved_url = data.get("resolved_url", "")
    has_content = bool(data.get("content", "").strip())
    is_error = data.get("content", "").startswith("[Error") if has_content else False
    is_same_url = (link == resolved_url) or (resolved_url == "")
    content_length = len(data.get("content", ""))

    rows.append({
        "title": data.get("title", "N/A"),
        "company_name": data.get("company_name", "N/A"),
        "keyword": data.get("keyword", "N/A"),
        "published": data.get("published", "N/A"),
        "source": data.get("source", "N/A"),
        "original_link": link,
        "resolved_url": resolved_url,
        "url_resolved": not is_same_url,
        "has_content": has_content and not is_error,
        "is_error": is_error,
        "content_length": content_length,
        "scraped_at": data.get("scraped_at", "N/A"),
    })

df = pd.DataFrame(rows)

# -----------------------------
# Summary Metrics
# -----------------------------
st.subheader("📊 Summary")

col1, col2, col3, col4 = st.columns(4)
col1.metric("📰 Total Articles", len(df))
col2.metric(
    "✅ URL Resolved",
    len(df[df["url_resolved"] == True]),
    delta=f"{len(df[df['url_resolved'] == False])} not resolved",
    delta_color="inverse"
)
col3.metric(
    "📄 Has Content",
    len(df[df["has_content"] == True]),
    delta=f"{len(df[df['has_content'] == False])} missing",
    delta_color="inverse"
)
col4.metric("❌ Scrape Errors", len(df[df["is_error"] == True]))

# -----------------------------
# URL Resolution Check
# -----------------------------
st.markdown("---")
st.subheader("🔗 URL Resolution Status")

tab1, tab2, tab3 = st.tabs(["All Articles", "⚠️ Not Resolved", "✅ Resolved"])

def style_url_table(df_display):
    def highlight_row(row):
        if not row["url_resolved"]:
            return ["background-color: #fff3cd"] * len(row)
        return [""] * len(row)
    return df_display.style.apply(highlight_row, axis=1)

display_cols = ["title", "source", "url_resolved", "has_content", "is_error", "content_length", "scraped_at"]

with tab1:
    st.dataframe(
        df[display_cols].reset_index(drop=True),
        use_container_width=True,
        column_config={
            "url_resolved": st.column_config.CheckboxColumn("URL Resolved ✅"),
            "has_content": st.column_config.CheckboxColumn("Has Content 📄"),
            "is_error": st.column_config.CheckboxColumn("Error ❌"),
            "content_length": st.column_config.NumberColumn("Content Length", format="%d chars"),
        }
    )

with tab2:
    not_resolved = df[df["url_resolved"] == False]
    if not_resolved.empty:
        st.success("✅ All URLs were successfully resolved!")
    else:
        st.warning(f"⚠️ {len(not_resolved)} articles still pointing to Google News URL (redirect failed)")
        st.dataframe(
            not_resolved[["title", "source", "original_link", "resolved_url"]].reset_index(drop=True),
            use_container_width=True
        )

with tab3:
    resolved = df[df["url_resolved"] == True]
    st.info(f"✅ {len(resolved)} articles successfully redirected to actual publisher URL")
    st.dataframe(
        resolved[["title", "source", "original_link", "resolved_url"]].reset_index(drop=True),
        use_container_width=True
    )

# -----------------------------
# URL Comparison Detail
# -----------------------------
st.markdown("---")
st.subheader("🔍 URL Comparison Detail")

selected_title = st.selectbox(
    "Select an article to inspect:",
    df["title"].tolist()
)

selected_row = df[df["title"] == selected_title].iloc[0]
data_entry = scraped_data.get(selected_row["original_link"], {})

col_a, col_b = st.columns(2)

with col_a:
    st.markdown("**🔗 Original Google RSS Link**")
    st.code(selected_row["original_link"], language="text")

with col_b:
    st.markdown("**🌐 Resolved Article URL**")
    if selected_row["url_resolved"]:
        st.code(selected_row["resolved_url"], language="text")
        st.success("✅ Redirect successful — URL was resolved to actual publisher")
    else:
        st.code(selected_row["resolved_url"] or "N/A", language="text")
        st.error("❌ Redirect failed — still pointing to Google News")

# Metadata
st.markdown("#### 📌 Article Metadata")
meta_col1, meta_col2, meta_col3, meta_col4 = st.columns(4)
meta_col1.metric("Company", selected_row["company_name"])
meta_col2.metric("Keyword", selected_row["keyword"])
meta_col3.metric("Source", selected_row["source"])
meta_col4.metric("Content Length", f"{selected_row['content_length']} chars")

# Content Preview
st.markdown("#### 📄 Scraped Content Preview")
content = data_entry.get("content", "")

if not content:
    st.warning("⏳ No content scraped for this article.")
elif content.startswith("[Error"):
    st.error(f"❌ Scraping failed: {content}")
else:
    st.success(f"✅ Content available ({len(content)} characters)")
    with st.expander("View Full Content", expanded=False):
        st.text_area("Content", content, height=400, label_visibility="collapsed")

# -----------------------------
# Export
# -----------------------------
st.markdown("---")
st.subheader("📥 Export")

export_df = df[[
    "title", "company_name", "keyword", "source", "published",
    "url_resolved", "has_content", "is_error", "content_length",
    "original_link", "resolved_url", "scraped_at"
]]

st.download_button(
    label="⬇️ Download URL Report as CSV",
    data=export_df.to_csv(index=False),
    file_name="url_resolution_report.csv",
    mime="text/csv"
)
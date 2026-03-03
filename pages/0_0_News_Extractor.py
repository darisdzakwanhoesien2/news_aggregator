# pages/News_Extractor.py

import streamlit as st
import json
import pandas as pd
import re
from bs4 import BeautifulSoup
from datetime import datetime

st.set_page_config(page_title="News Extractor", layout="wide")

st.title("📰 ESG News Extractor")

# -----------------------------
# Load Data
# -----------------------------
@st.cache_data
def load_data():
    with open("data/news_dataset_new.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return pd.DataFrame(data)

df = load_data()

# -----------------------------
# Clean HTML from summary
# -----------------------------
def clean_html(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ").strip()

df["clean_summary"] = df["summary"].apply(clean_html)

# Convert published date
df["published"] = pd.to_datetime(df["published"], errors="coerce")

# -----------------------------
# Sidebar Filters
# -----------------------------
st.sidebar.header("Filter Options")

company_filter = st.sidebar.selectbox(
    "Select Company",
    ["All"] + sorted(df["company_name"].dropna().unique().tolist())
)

keyword_filter = st.sidebar.selectbox(
    "Select Keyword",
    ["All"] + sorted(df["keyword"].dropna().unique().tolist())
)

date_range = st.sidebar.date_input(
    "Select Date Range",
    []
)

filtered_df = df.copy()

if company_filter != "All":
    filtered_df = filtered_df[filtered_df["company_name"] == company_filter]

if keyword_filter != "All":
    filtered_df = filtered_df[filtered_df["keyword"] == keyword_filter]

if len(date_range) == 2:
    filtered_df = filtered_df[
        (filtered_df["published"].dt.date >= date_range[0]) &
        (filtered_df["published"].dt.date <= date_range[1])
    ]

st.subheader(f"Found {len(filtered_df)} Articles")

# -----------------------------
# Display Articles
# -----------------------------
for idx, row in filtered_df.iterrows():
    with st.container():
        st.markdown(f"### {row['title']}")
        st.markdown(f"**Source:** {row['source']}")
        st.markdown(f"**Published:** {row['published']}")
        st.markdown(f"**Company:** {row['company_name']} ({row['company_code']})")
        st.markdown(f"**ESG Score:** {row['esg_score']}")
        st.markdown("---")
        st.write(row["clean_summary"])
        st.markdown(f"[Read Full Article]({row['link']})")
        st.divider()

# -----------------------------
# Export Button
# -----------------------------
st.download_button(
    label="Download Filtered Data as CSV",
    data=filtered_df.to_csv(index=False),
    file_name="filtered_news.csv",
    mime="text/csv"
)
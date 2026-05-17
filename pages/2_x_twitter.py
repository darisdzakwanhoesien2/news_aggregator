import streamlit as st
import json
import os
from datetime import datetime
from scrapers.x_twitter import XTwitterScraper
from _page_descriptions import render_page_description

DATA_DIR = "data/x/posts"
os.makedirs(DATA_DIR, exist_ok=True)

st.set_page_config(layout="wide")
st.title("🐦 X (Twitter) Scraper")
render_page_description(__file__)

query = st.text_input(
    "Search query",
    value="DJ Mag Top 100"
)

limit = st.slider("Number of posts", 1, 100, 20)

if st.button("🚀 Scrape X"):
    scraper = XTwitterScraper()

    with st.spinner("Scraping X..."):
        posts = scraper.fetch_posts(query, limit)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"{DATA_DIR}/x_posts_{ts}.json"

    with open(path, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)

    st.success("✅ Scraping completed")
    st.metric("Posts scraped", len(posts))
    st.dataframe(posts)

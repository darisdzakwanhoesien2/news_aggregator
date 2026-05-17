import streamlit as st
import pandas as pd
from utils.playwright_client import fetch_posts_playwright
from utils.storage import save_posts
from _page_descriptions import render_page_description

st.set_page_config(layout="wide")
st.title("⚠️ Instagram Scraper — Playwright")
render_page_description(__file__)

st.warning("""
This method uses browser automation.
It is slower and more likely to be blocked.
Use only if Instaloader fails.
""")

username = st.text_input("Instagram username", placeholder="natgeo")
scrolls = st.slider("Scroll depth", 1, 15, 5)

if st.button("Scrape with Playwright"):
    if not username:
        st.warning("Please enter a username.")
        st.stop()

    with st.spinner("Launching browser & scraping..."):
        posts = fetch_posts_playwright(username, scrolls)

    if not posts:
        st.error("No posts found or blocked.")
        st.stop()

    df = pd.DataFrame(posts)
    st.success(f"Fetched {len(df)} posts")

    st.dataframe(df, use_container_width=True)

    path = save_posts(username, posts)
    st.info(f"Saved to {path}")

    st.download_button(
        "⬇️ Download JSON",
        df.to_json(orient="records", indent=2),
        file_name=f"{username}_playwright_posts.json"
    )

import streamlit as st
import pandas as pd
from utils.instaloader_client import fetch_instagram_posts
from utils.storage import save_posts
from _page_descriptions import render_page_description

st.set_page_config(layout="wide")
st.title("📸 Instagram Scraper — Instaloader")
render_page_description(__file__)

username = st.text_input("Instagram username", placeholder="natgeo")
limit = st.slider("Number of posts", 5, 100, 20)

if st.button("Scrape with Instaloader"):
    if not username:
        st.warning("Please enter a username.")
        st.stop()

    with st.spinner("Scraping Instagram posts..."):
        posts = fetch_instagram_posts(username, limit)

    if not posts:
        st.error("No posts found or account is private.")
        st.stop()

    df = pd.DataFrame(posts)
    st.success(f"Fetched {len(df)} posts")

    st.dataframe(df, use_container_width=True)

    path = save_posts(username, posts)
    st.info(f"Saved to {path}")

    st.download_button(
        "⬇️ Download JSON",
        df.to_json(orient="records", indent=2),
        file_name=f"{username}_posts.json"
    )

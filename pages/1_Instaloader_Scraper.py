import streamlit as st
import pandas as pd
from utils.instaloader_client import (
    InstagramScraperError,
    fetch_instagram_posts,
    normalize_instagram_username,
)
from utils.storage import save_instagram_posts
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

    try:
        normalized_username = normalize_instagram_username(username)
        with st.spinner("Scraping Instagram posts..."):
            posts = fetch_instagram_posts(normalized_username, limit)
    except InstagramScraperError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:
        st.error(f"Failed to scrape Instagram posts: {exc}")
        st.stop()

    if not posts:
        st.warning(f"No public posts found for '{normalized_username}'.")
        st.stop()

    df = pd.DataFrame(posts)
    st.success(f"Fetched {len(df)} posts")

    st.dataframe(df, use_container_width=True)

    path = save_instagram_posts(normalized_username, posts)
    st.info(f"Saved to {path}")

    st.download_button(
        "⬇️ Download JSON",
        df.to_json(orient="records", indent=2),
        file_name=f"{normalized_username}_posts.json"
    )

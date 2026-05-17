import streamlit as st
import pandas as pd

from ingestors.x_api_ingestor import fetch_user_tweets
from ingestors.x_playwright_ingestor import fetch_tweets_incremental
from utils.storage import save_x_posts, load_existing_x_post_ids
from _page_descriptions import render_page_description

# =====================================================
# Page config
# =====================================================
st.set_page_config(
    page_title="🐦 X (Twitter) ESG Scraper",
    layout="wide"
)

st.title("🐦 X (Twitter) ESG Scraper")
render_page_description(__file__)
st.markdown("""
Incrementally scrape **X (Twitter)** posts for ESG monitoring.

- Already-scraped posts are **skipped**
- Older posts are **automatically discovered**
- Safe to re-run anytime
""")

# =====================================================
# Inputs
# =====================================================
username = st.text_input("X Username", placeholder="walhinasional")

method = st.radio(
    "Scraping Method",
    [
        "API (Official – limited)",
        "Playwright (Incremental – recommended)"
    ]
)

limit = st.slider(
    "Max posts (API only)",
    min_value=5,
    max_value=50,
    value=10
)

max_scrolls = st.slider(
    "Max scroll depth (Playwright)",
    min_value=5,
    max_value=50,
    value=30
)

source_type = st.selectbox(
    "Source Type",
    ["ngo", "company", "media"],
    index=0
)

# =====================================================
# Scrape action
# =====================================================
if st.button("🚀 Scrape X"):
    if not username:
        st.warning("Please enter a username.")
        st.stop()

    with st.spinner("Scraping X… please wait"):
        # ---------------------------------------------
        # Load existing post IDs (for incremental scrape)
        # ---------------------------------------------
        existing_ids = load_existing_x_post_ids(username)

        # ---------------------------------------------
        # API METHOD
        # ---------------------------------------------
        if method.startswith("API"):
            posts = fetch_user_tweets(
                username=username,
                max_results=limit,
                source_type=source_type
            )

        # ---------------------------------------------
        # PLAYWRIGHT INCREMENTAL METHOD
        # ---------------------------------------------
        else:
            posts = fetch_tweets_incremental(
                username=username,
                existing_ids=existing_ids,
                max_scrolls=max_scrolls,
                source_type=source_type
            )

    # =================================================
    # Results handling
    # =================================================
    if not posts:
        st.warning("No new posts found (already fully scraped or restricted).")
        st.stop()

    df = pd.DataFrame(posts)

    st.success(f"✅ Scraped {len(df)} NEW posts")

    # Show quick metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("New Posts", len(df))
    c2.metric("Previously Scraped", len(existing_ids))
    c3.metric("Total After Save", len(existing_ids) + len(df))

    # =================================================
    # Preview
    # =================================================
    st.subheader("📄 New Posts Preview")

    preview_cols = [
        "post_id",
        "content",
        "likes",
        "comments",
        "shares",
        "metrics_source",
        "scraped_at",
        "url",
    ]

    available_cols = [c for c in preview_cols if c in df.columns]

    st.dataframe(
        df[available_cols],
        use_container_width=True
    )

    # =================================================
    # Save
    # =================================================
    path = save_x_posts(username, posts)

    st.info(f"💾 Saved new posts to `{path}`")

    # =================================================
    # Download
    # =================================================
    st.download_button(
        "⬇️ Download NEW posts (JSON)",
        data=df.to_json(orient="records", indent=2, ensure_ascii=False),
        file_name=f"x_{username}_new.json"
    )


# import streamlit as st
# import pandas as pd
# from ingestors.x_api_ingestor import fetch_user_tweets
# from ingestors.x_playwright_ingestor import fetch_tweets_playwright
# from utils.storage import save_x_posts

# st.set_page_config(layout="wide")
# st.title("🐦 X (Twitter) ESG Scraper")

# username = st.text_input("X Username", placeholder="walhinasional")
# method = st.radio("Scraping Method", ["API (Official)", "Playwright (Fallback)"])
# limit = st.slider("Max posts", 5, 50, 10)

# if st.button("Scrape X"):
#     if not username:
#         st.warning("Enter a username")
#         st.stop()

#     with st.spinner("Scraping X..."):
#         if method == "API (Official)":
#             posts = fetch_user_tweets(username, limit)
#         else:
#             posts = fetch_tweets_playwright(username)

#     if not posts:
#         st.error("No posts retrieved.")
#         st.stop()

#     df = pd.DataFrame(posts)
#     st.success(f"Fetched {len(df)} posts")

#     st.dataframe(df, use_container_width=True)

#     path = save_x_posts(username, posts)
#     st.info(f"Saved to {path}")

#     st.download_button(
#         "⬇️ Download JSON",
#         df.to_json(orient="records", indent=2),
#         file_name=f"x_{username}.json"
#     )

import streamlit as st
import requests
import feedparser
import json
import time
from pathlib import Path
from urllib.parse import quote_plus
import pandas as pd
from _page_descriptions import render_page_description

# =========================================================
# CONFIG
# =========================================================

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

OUTPUT_JSON = DATA_DIR / "news_dataset.json"

DEFAULT_QUERY = "financial regulation AI audit"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml",
}

REQUEST_TIMEOUT = 20

# =========================================================
# STORAGE
# =========================================================

def load_existing():
    if OUTPUT_JSON.exists():
        try:
            with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_records(new_rows):
    existing = load_existing()

    # Deduplicate by decoded_url
    seen = {
        row.get("decoded_url")
        for row in existing
        if row.get("decoded_url")
    }

    clean_new = [
        row for row in new_rows
        if row.get("decoded_url") not in seen
    ]

    combined = existing + clean_new

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)

    return clean_new, combined


# =========================================================
# PIPELINE FUNCTIONS
# =========================================================

def build_search_rss(query, language, country):
    encoded_query = quote_plus(query)
    return (
        f"https://news.google.com/rss/search?"
        f"q={encoded_query}&hl={language}&gl={country}&ceid={country}:{language}"
    )


def fetch_articles_from_query(query, language, country, limit):
    rss_url = build_search_rss(query, language, country)
    feed = feedparser.parse(rss_url)

    rows = []
    for idx, entry in enumerate(feed.entries[:limit], start=1):
        rows.append({
            "query": query,
            "id": idx,
            "title": entry.get("title"),
            "link": entry.get("link"),
            "published": entry.get("published"),
            "summary": entry.get("summary"),
            "source": entry.get("source", {}).get("title"),
        })

    return rows, rss_url


def resolve_google_redirect(url):
    """
    Resolves Google News redirect safely using HTTP redirects.
    """
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )
        return r.url
    except Exception as e:
        print("Redirect error:", e)
        return None


# =========================================================
# STREAMLIT UI
# =========================================================

st.set_page_config(layout="wide")
st.title("🔎 Google News Query Collector → JSON Dataset")
render_page_description(__file__)

st.caption("Search-driven dataset builder for research pipelines")

# ---------------- Sidebar Controls ----------------

with st.sidebar:
    st.header("⚙️ Search Settings")

    query = st.text_input("Search query", DEFAULT_QUERY)

    col1, col2 = st.columns(2)
    with col1:
        language = st.selectbox("Language", ["en", "it", "de", "fr"], index=0)
    with col2:
        country = st.selectbox("Country", ["US", "IT", "DE", "FR"], index=0)

    limit = st.slider("Max articles", 1, 50, 15)

    batch_size = st.slider("Batch size", 1, 10, 5)

    delay = st.slider("Delay between batches (seconds)", 0.0, 5.0, 1.0)

    run_btn = st.button("🚀 Run Search")

# =========================================================
# RUN PIPELINE
# =========================================================

if run_btn:
    if not query.strip():
        st.warning("Please enter a search query.")
        st.stop()

    st.info("📡 Querying Google News RSS...")
    articles, rss_url = fetch_articles_from_query(
        query=query,
        language=language,
        country=country,
        limit=limit
    )

    st.caption(f"RSS Source: {rss_url}")

    if not articles:
        st.error("No articles found.")
        st.stop()

    st.success(f"Found {len(articles)} articles")

    progress = st.progress(0)
    decoded_rows = []
    total = len(articles)

    for batch_start in range(0, total, batch_size):
        batch = articles[batch_start:batch_start + batch_size]

        for article in batch:
            title = article["title"]
            encoded_url = article["link"]

            st.write(f"🔎 Resolving: {title}")

            decoded_url = resolve_google_redirect(encoded_url)

            row = {
                **article,
                "decoded_url": decoded_url,
                "status": "ok" if decoded_url else "failed"
            }

            decoded_rows.append(row)
            progress.progress(len(decoded_rows) / total)

        if delay > 0:
            time.sleep(delay)

    # =====================================================
    # SAVE
    # =====================================================

    new_rows, all_rows = save_records(decoded_rows)

    st.success(f"✅ Saved {len(new_rows)} new records")
    st.caption(f"JSON path: {OUTPUT_JSON.resolve()}")

    # =====================================================
    # DISPLAY
    # =====================================================

    st.subheader("📊 Latest Search Results")
    st.dataframe(pd.DataFrame(decoded_rows), use_container_width=True)

    with st.expander("📦 Raw JSON (latest run)"):
        st.json(decoded_rows)

# =========================================================
# STORED DATA VIEW
# =========================================================

st.divider()
st.subheader("📚 Stored Dataset")

stored = load_existing()
st.write(f"Total stored records: {len(stored)}")

if stored:
    df_all = pd.DataFrame(stored)

    st.dataframe(df_all, use_container_width=True)

    st.download_button(
        "⬇️ Download JSON Dataset",
        json.dumps(stored, indent=2, ensure_ascii=False),
        file_name="news_dataset.json",
        mime="application/json"
    )


# import streamlit as st
# import requests
# import feedparser
# import json
# import time
# from pathlib import Path
# import pandas as pd

# # =========================================================
# # CONFIG
# # =========================================================

# DATA_DIR = Path("data")
# DATA_DIR.mkdir(exist_ok=True)

# OUTPUT_JSON = DATA_DIR / "decoded_news.json"

# DEFAULT_RSS = "https://news.google.com/rss?hl=it&gl=IT&ceid=IT:it"

# HEADERS = {
#     "User-Agent": "Mozilla/5.0",
#     "Accept": "text/html,application/xhtml+xml",
# }

# REQUEST_TIMEOUT = 20

# # =========================================================
# # STORAGE
# # =========================================================

# def load_existing():
#     if OUTPUT_JSON.exists():
#         try:
#             with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
#                 return json.load(f)
#         except Exception:
#             return []
#     return []


# def save_records(new_rows):
#     existing = load_existing()

#     # Deduplicate by decoded_url
#     seen = {row.get("decoded_url") for row in existing if row.get("decoded_url")}
#     clean_new = [
#         row for row in new_rows
#         if row.get("decoded_url") not in seen
#     ]

#     combined = existing + clean_new

#     with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
#         json.dump(combined, f, indent=2, ensure_ascii=False)

#     return clean_new, combined


# # =========================================================
# # PIPELINE FUNCTIONS
# # =========================================================

# def fetch_rss_articles(rss_url, limit):
#     feed = feedparser.parse(rss_url)

#     rows = []
#     for idx, entry in enumerate(feed.entries[:limit], start=1):
#         rows.append({
#             "id": idx,
#             "title": entry.get("title"),
#             "link": entry.get("link"),
#             "published": entry.get("published"),
#             "summary": entry.get("summary"),
#             "source": entry.get("source", {}).get("title"),
#         })

#     return rows


# def resolve_google_redirect(url):
#     """
#     Resolves Google News redirect safely using HTTP redirects.
#     """
#     try:
#         r = requests.get(
#             url,
#             headers=HEADERS,
#             timeout=REQUEST_TIMEOUT,
#             allow_redirects=True
#         )
#         return r.url
#     except Exception as e:
#         print("Redirect error:", e)
#         return None


# # =========================================================
# # STREAMLIT UI
# # =========================================================

# st.set_page_config(layout="wide")
# st.title("🗞️ Google News RSS → URL Resolver → JSON Store")

# st.caption("Reliable replacement for fragile Google decoding workflows")

# # ---------------- Sidebar Controls ----------------

# with st.sidebar:
#     st.header("⚙️ Pipeline Settings")

#     rss_url = st.text_input("RSS Feed URL", DEFAULT_RSS)

#     limit = st.slider("Number of articles", 1, 50, 10)

#     batch_size = st.slider("Batch size", 1, 10, 3)

#     delay = st.slider("Delay between batches (seconds)", 0.0, 5.0, 1.0)

#     run_btn = st.button("🚀 Run Pipeline")

# # =========================================================
# # RUN PIPELINE
# # =========================================================

# if run_btn:
#     st.info("📡 Fetching RSS feed...")
#     articles = fetch_rss_articles(rss_url, limit)

#     if not articles:
#         st.error("No RSS entries found.")
#         st.stop()

#     st.success(f"Loaded {len(articles)} RSS articles")

#     progress = st.progress(0)
#     decoded_rows = []
#     total = len(articles)

#     for batch_start in range(0, total, batch_size):
#         batch = articles[batch_start:batch_start + batch_size]

#         for article in batch:
#             title = article["title"]
#             encoded_url = article["link"]

#             st.write(f"🔎 Resolving: {title}")

#             decoded_url = resolve_google_redirect(encoded_url)

#             row = {
#                 **article,
#                 "decoded_url": decoded_url,
#                 "status": "ok" if decoded_url else "failed"
#             }

#             decoded_rows.append(row)

#             progress.progress(len(decoded_rows) / total)

#         if delay > 0:
#             time.sleep(delay)

#     # =====================================================
#     # SAVE
#     # =====================================================

#     new_rows, all_rows = save_records(decoded_rows)

#     st.success(f"✅ Saved {len(new_rows)} new records")
#     st.caption(f"JSON path: {OUTPUT_JSON.resolve()}")

#     # =====================================================
#     # DISPLAY
#     # =====================================================

#     st.subheader("📊 Latest Run Results")
#     st.dataframe(pd.DataFrame(decoded_rows), use_container_width=True)

#     with st.expander("📦 Raw JSON (latest run)"):
#         st.json(decoded_rows)

# # =========================================================
# # STORED DATA VIEW
# # =========================================================

# st.divider()
# st.subheader("📚 Stored Dataset")

# stored = load_existing()
# st.write(f"Total stored records: {len(stored)}")

# if stored:
#     df_all = pd.DataFrame(stored)
#     st.dataframe(df_all, use_container_width=True)

#     st.download_button(
#         "⬇️ Download JSON",
#         json.dumps(stored, indent=2, ensure_ascii=False),
#         file_name="decoded_news.json",
#         mime="application/json"
#     )

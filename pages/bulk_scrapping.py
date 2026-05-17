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

DEFAULT_QUERIES = """ESG disclosure audit
greenwashing detection NLP
financial reasoning LLM
multilingual regulatory compliance
symbolic AI finance
"""

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
            "rss_url": rss_url,
        })

    return rows


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
    except Exception:
        return None


# =========================================================
# STREAMLIT UI
# =========================================================

st.set_page_config(layout="wide")
st.title("🔎 Bulk Google News Query Collector → JSON Dataset")
render_page_description(__file__)

st.caption("Multi-query dataset builder for large-scale research")

# ---------------- Sidebar Controls ----------------

with st.sidebar:
    st.header("⚙️ Bulk Query Settings")

    queries_text = st.text_area(
        "Enter one query per line",
        DEFAULT_QUERIES,
        height=180
    )

    col1, col2 = st.columns(2)
    with col1:
        language = st.selectbox("Language", ["en", "it", "de", "fr"], index=0)
    with col2:
        country = st.selectbox("Country", ["US", "IT", "DE", "FR"], index=0)

    limit = st.slider("Articles per query", 1, 50, 10)

    batch_size = st.slider("Batch size", 1, 10, 5)

    delay = st.slider("Delay between batches (seconds)", 0.0, 5.0, 1.0)

    run_btn = st.button("🚀 Run Bulk Search")

# =========================================================
# RUN PIPELINE
# =========================================================

if run_btn:
    queries = [q.strip() for q in queries_text.splitlines() if q.strip()]

    if not queries:
        st.warning("Please enter at least one query.")
        st.stop()

    st.info(f"🔍 Running {len(queries)} queries...")

    all_decoded_rows = []
    query_progress = st.progress(0)
    completed_queries = 0

    for query in queries:
        st.subheader(f"🧭 Query: {query}")

        articles = fetch_articles_from_query(
            query=query,
            language=language,
            country=country,
            limit=limit
        )

        if not articles:
            st.warning("No results found.")
            completed_queries += 1
            query_progress.progress(completed_queries / len(queries))
            continue

        st.write(f"Found {len(articles)} articles")

        progress = st.progress(0)
        total = len(articles)
        decoded_rows = []

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
                all_decoded_rows.append(row)
                progress.progress(len(decoded_rows) / total)

            if delay > 0:
                time.sleep(delay)

        completed_queries += 1
        query_progress.progress(completed_queries / len(queries))

    # =====================================================
    # SAVE
    # =====================================================

    new_rows, all_rows = save_records(all_decoded_rows)

    st.success(f"✅ Saved {len(new_rows)} new records from bulk run")
    st.caption(f"JSON path: {OUTPUT_JSON.resolve()}")

    # =====================================================
    # DISPLAY
    # =====================================================

    st.subheader("📊 Bulk Run Results")
    st.dataframe(pd.DataFrame(all_decoded_rows), use_container_width=True)

    with st.expander("📦 Raw JSON (bulk run)"):
        st.json(all_decoded_rows)

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

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

DATASET_JSON = DATA_DIR / "news_dataset.json"
COMPANIES_JSON = DATA_DIR / "esg_companies.json"
KEYWORDS_JSON = DATA_DIR / "esg_keywords.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml",
}

REQUEST_TIMEOUT = 20


# =========================================================
# LOADERS
# =========================================================

def load_json(path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def load_companies():
    return load_json(COMPANIES_JSON, [])


def load_keywords():
    return load_json(KEYWORDS_JSON, {})


# =========================================================
# STORAGE
# =========================================================

def load_existing_dataset():
    return load_json(DATASET_JSON, [])


def save_dataset(new_rows):
    existing = load_existing_dataset()

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

    with open(DATASET_JSON, "w", encoding="utf-8") as f:
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
            "title": entry.get("title"),
            "link": entry.get("link"),
            "published": entry.get("published"),
            "summary": entry.get("summary"),
            "source": entry.get("source", {}).get("title"),
            "rss_url": rss_url,
        })

    return rows


def resolve_google_redirect(url):
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
# QUERY GENERATION
# =========================================================

def build_queries(selected_companies, companies, keywords):
    """
    Generates structured queries:
    Company → keywords → queries
    """
    queries = []

    for company in companies:
        if company["code"] not in selected_companies:
            continue

        code = company["code"]
        name = company["company_name"]
        esg_score = company["esg_score"]

        kws = keywords.get(code, [])

        for kw in kws:
            queries.append({
                "company_code": code,
                "company_name": name,
                "esg_score": esg_score,
                "keyword": kw,
                "query": kw
            })

    return queries


# =========================================================
# STREAMLIT UI
# =========================================================

st.set_page_config(layout="wide")
st.title("🌱 ESG Company → Keyword → News Scraper")
render_page_description(__file__)

st.caption("Bulk ESG news harvesting with company-aware provenance")

# ---------------- Sidebar Controls ----------------

with st.sidebar:
    st.header("🏢 Company Selection")

    companies = load_companies()
    keywords = load_keywords()

    if not companies:
        st.error("Missing data/esg_companies.json")
        st.stop()

    company_map = {
        f"{c['code']} — {c['company_name']}": c["code"]
        for c in companies
    }

    selected_labels = st.multiselect(
        "Select companies",
        list(company_map.keys()),
        default=list(company_map.keys())[:2]
    )

    selected_codes = [company_map[label] for label in selected_labels]

    st.divider()
    st.header("⚙️ Scraping Settings")

    col1, col2 = st.columns(2)
    with col1:
        language = st.selectbox("Language", ["en", "id", "it"], index=0)
    with col2:
        country = st.selectbox("Country", ["US", "ID", "IT"], index=0)

    limit = st.slider("Articles per keyword", 1, 100, 5)
    batch_size = st.slider("Batch size", 1, 10, 5)
    delay = st.slider("Delay between batches (seconds)", 0.0, 3.0, 1.0)

    run_btn = st.button("🚀 Run Company Scraping")

# =========================================================
# RUN PIPELINE
# =========================================================

if run_btn:
    companies_data = load_companies()
    keywords_data = load_keywords()

    queries = build_queries(
        selected_companies=selected_codes,
        companies=companies_data,
        keywords=keywords_data
    )

    if not queries:
        st.warning("No keywords found for selected companies.")
        st.stop()

    st.success(f"Generated {len(queries)} keyword queries")

    all_rows = []
    global_progress = st.progress(0)

    for q_index, q in enumerate(queries, start=1):
        st.subheader(f"🔎 {q['company_name']} → {q['keyword']}")

        articles = fetch_articles_from_query(
            query=q["query"],
            language=language,
            country=country,
            limit=limit
        )

        if not articles:
            st.warning("No articles found.")
            global_progress.progress(q_index / len(queries))
            continue

        local_progress = st.progress(0)
        total = len(articles)
        decoded = []

        for batch_start in range(0, total, batch_size):
            batch = articles[batch_start:batch_start + batch_size]

            for article in batch:
                decoded_url = resolve_google_redirect(article["link"])

                row = {
                    **article,
                    **q,
                    "decoded_url": decoded_url,
                    "status": "ok" if decoded_url else "failed"
                }

                decoded.append(row)
                all_rows.append(row)
                local_progress.progress(len(decoded) / total)

            if delay > 0:
                time.sleep(delay)

        global_progress.progress(q_index / len(queries))

    # =====================================================
    # SAVE DATASET
    # =====================================================

    new_rows, combined = save_dataset(all_rows)

    st.success(f"✅ Saved {len(new_rows)} new records")

    # =====================================================
    # DISPLAY
    # =====================================================

    st.subheader("📊 Latest Scraped Records")
    st.dataframe(pd.DataFrame(new_rows), use_container_width=True)

    with st.expander("📦 Raw JSON"):
        st.json(new_rows)

# =========================================================
# STORED DATA VIEW
# =========================================================

st.divider()
st.subheader("📚 ESG News Dataset")

stored = load_existing_dataset()
st.write(f"Total stored records: {len(stored)}")

if stored:
    df_all = pd.DataFrame(stored)
    st.dataframe(df_all, use_container_width=True)

    st.download_button(
        "⬇️ Download Dataset JSON",
        json.dumps(stored, indent=2, ensure_ascii=False),
        file_name="news_dataset.json",
        mime="application/json"
    )

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

BASE_DIR = Path(__file__).resolve().parents[1]

DATA_DIR = BASE_DIR / "data"
DATASET_JSON = DATA_DIR / "news_dataset.json"
COMPANIES_JSON = DATA_DIR / "esg_companies.json"
KEYWORDS_JSON = DATA_DIR / "esg_keywords.json"
MISSING_CODES_JSON = DATA_DIR / "missing_companies.json"

DATA_DIR.mkdir(exist_ok=True)

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
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def load_companies():
    return load_json(COMPANIES_JSON, [])


def load_keywords():
    return load_json(KEYWORDS_JSON, {})


def load_missing_codes():
    data = load_json(MISSING_CODES_JSON, {})
    return data.get("missing_codes", [])

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
        if row.get("decoded_url") and row.get("decoded_url") not in seen
    ]

    combined = existing + clean_new

    with open(DATASET_JSON, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)

    return len(clean_new)


# =========================================================
# PIPELINE
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
    for entry in feed.entries[:limit]:
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


def build_queries(missing_codes, companies, keywords):
    queries = []

    for company in companies:
        if company["code"] not in missing_codes:
            continue

        kws = keywords.get(company["code"], [])

        for kw in kws:
            queries.append({
                "company_code": company["code"],
                "company_name": company["company_name"],
                "keyword": kw,
                "query": kw
            })

    return queries

# =========================================================
# STREAMLIT UI
# =========================================================

st.set_page_config(layout="wide")
st.title("🚀 Auto ESG News Scraper")
render_page_description(__file__)
st.caption("Automatically scrapes companies missing from dataset")

missing_codes = load_missing_codes()
companies = load_companies()
keywords = load_keywords()

if not missing_codes:
    st.success("🎉 No missing companies detected!")
    st.stop()

st.warning(f"⚠️ {len(missing_codes)} companies pending scraping")
st.code(", ".join(missing_codes))

language = st.selectbox("Language", ["en", "id"], index=0)
country = st.selectbox("Country", ["US", "ID"], index=0)
limit = st.slider("Articles per keyword", 1, 200, 10)
batch_size = st.slider("Batch size", 1, 10, 5)
delay = st.slider("Delay between batches (seconds)", 0.0, 2.0, 1.0)

run_btn = st.button("🚀 Run Auto Scraper")

# =========================================================
# RUN
# =========================================================

if run_btn:

    queries = build_queries(
        missing_codes=missing_codes,
        companies=companies,
        keywords=keywords
    )

    if not queries:
        st.warning("No keywords available for missing companies.")
        st.stop()

    st.success(f"Generated {len(queries)} queries")

    progress = st.progress(0)
    total_saved = 0

    for i, q in enumerate(queries, 1):
        st.write(f"🔎 {q['company_code']} → {q['keyword']}")

        articles = fetch_articles_from_query(
            q["query"], language, country, limit
        )

        rows = []
        for article in articles:
            decoded = resolve_google_redirect(article["link"])
            rows.append({
                **article,
                **q,
                "decoded_url": decoded,
            })

        saved = save_dataset(rows)
        total_saved += saved

        progress.progress(i / len(queries))
        time.sleep(delay)

    st.success(f"🎉 Auto scrape completed — {total_saved} new records added")

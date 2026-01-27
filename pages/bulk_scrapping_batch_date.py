import streamlit as st
import requests
import feedparser
import json
import time
from pathlib import Path
from urllib.parse import quote_plus
import pandas as pd
from datetime import datetime
import uuid

# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(layout="wide")
st.title("🌱 ESG Company → Keyword → News Scraper")
st.caption("Date-filtered • Incremental • Logged • Reproducible")

# =========================================================
# CONFIG
# =========================================================

BASE_DIR = Path(__file__).resolve().parents[1]

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

DATASET_JSON   = DATA_DIR / "news_dataset_new_v2.json"
COMPANIES_JSON = DATA_DIR / "esg_companies.json"
KEYWORDS_JSON  = DATA_DIR / "esg_keywords_flat.json" # "esg_keywords.json"

LOG_FILE = LOG_DIR / "scraper_runs_v2.jsonl"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml",
}

REQUEST_TIMEOUT = 20

# =========================================================
# 🔄 REFRESH HANDLER
# =========================================================

def refresh_app():
    st.cache_data.clear()
    st.cache_resource.clear()
    st.experimental_rerun()

# Top toolbar refresh
col_refresh, col_spacer = st.columns([1, 10])
with col_refresh:
    if st.button("🔄 Refresh Data"):
        refresh_app()

# =========================================================
# LOGGING
# =========================================================

def log_event(event_type, payload):
    record = {
        "event": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        **payload
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record

# =========================================================
# LOADERS (CACHED)
# =========================================================

@st.cache_data
def load_json(path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


@st.cache_data
def load_companies():
    return load_json(COMPANIES_JSON, [])


@st.cache_data
def load_keywords():
    return load_json(KEYWORDS_JSON, {})


@st.cache_data
def load_existing_dataset():
    return load_json(DATASET_JSON, [])

# =========================================================
# STORAGE
# =========================================================

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

    return clean_new, combined


def append_rows_immediately(rows):
    if not rows:
        return 0
    new_rows, _ = save_dataset(rows)
    return len(new_rows)

# =========================================================
# HELPERS
# =========================================================

def parse_published_date(raw_date):
    try:
        return pd.to_datetime(raw_date, utc=True)
    except Exception:
        return pd.NaT


def build_search_rss(query, language, country):
    encoded_query = quote_plus(query)
    return (
        f"https://news.google.com/rss/search?"
        f"q={encoded_query}&hl={language}&gl={country}&ceid={country}:{language}"
    )


def resolve_google_redirect(url):
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )
        return r.url
    except Exception as e:
        log_event("redirect_error", {"url": url, "error": str(e)})
        return None

# =========================================================
# QUERY GENERATION
# =========================================================

def build_queries(selected_companies, companies, keywords):
    queries = []
    for company in companies:
        if company["code"] not in selected_companies:
            continue

        kws = keywords.get(company["code"], [])
        for kw in kws:
            queries.append({
                "company_code": company["code"],
                "company_name": company["company_name"],
                "esg_score": company.get("esg_score"),
                "keyword": kw,
                "query": kw
            })

    return queries

# =========================================================
# FETCHER WITH DATE FILTERING
# =========================================================

def fetch_articles_from_query(
    query,
    language,
    country,
    limit,
    date_from,
    date_to,
):
    rss_url = build_search_rss(query, language, country)
    feed = feedparser.parse(rss_url)

    rows = []

    date_from = pd.to_datetime(date_from, utc=True)
    date_to   = pd.to_datetime(date_to, utc=True) + pd.Timedelta(days=1)

    for entry in feed.entries[:limit]:
        published_raw = entry.get("published")
        published_dt = parse_published_date(published_raw)

        if pd.isna(published_dt):
            continue

        if not (date_from <= published_dt <= date_to):
            if published_dt < date_from:
                break
            continue

        rows.append({
            "query": query,
            "title": entry.get("title"),
            "link": entry.get("link"),
            "published": published_dt.isoformat(),
            "summary": entry.get("summary"),
            "source": entry.get("source", {}).get("title"),
            "rss_url": rss_url,
        })

    return rows

# =========================================================
# SIDEBAR
# =========================================================

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
        default=list(company_map.keys())[:3]
    )

    selected_codes = [company_map[label] for label in selected_labels]

    st.divider()
    st.header("⚙️ Scraping Settings")

    col1, col2 = st.columns(2)
    with col1:
        language = st.selectbox("Language", ["en", "id", "it"], index=0)
    with col2:
        country = st.selectbox("Country", ["US", "ID", "IT"], index=0)

    limit = st.slider("Articles per keyword", 1, 100, 20)
    batch_size = st.slider("Batch size", 1, 10, 5)
    delay = st.slider("Delay between batches (seconds)", 0.0, 3.0, 1.0)

    st.divider()
    st.header("📅 Date Filter")

    date_from = st.date_input("From date")
    date_to   = st.date_input("To date")

    run_btn = st.button("🚀 Run Company Scraping")

# =========================================================
# RUN PIPELINE
# =========================================================

if run_btn:
    if date_from > date_to:
        st.error("❌ From date must be earlier than To date.")
        st.stop()

    run_id = str(uuid.uuid4())

    log_event("run_started", {
        "run_id": run_id,
        "companies": selected_codes,
        "language": language,
        "country": country,
        "limit": limit,
        "batch_size": batch_size,
        "delay": delay,
        "date_from": str(date_from),
        "date_to": str(date_to),
    })

    queries = build_queries(
        selected_companies=selected_codes,
        companies=companies,
        keywords=keywords
    )

    if not queries:
        st.warning("No keywords found for selected companies.")
        st.stop()

    st.success(f"Generated {len(queries)} queries")

    global_progress = st.progress(0)
    total_saved = 0
    total_fetched = 0

    for q_index, q in enumerate(queries, start=1):
        st.subheader(f"🔎 {q['company_code']} → {q['keyword']}")

        articles = fetch_articles_from_query(
            query=q["query"],
            language=language,
            country=country,
            limit=limit,
            date_from=date_from,
            date_to=date_to,
        )

        fetched_count = len(articles)
        total_fetched += fetched_count

        log_event("query_fetched", {
            "run_id": run_id,
            "company_code": q["company_code"],
            "keyword": q["keyword"],
            "fetched": fetched_count,
        })

        if not articles:
            global_progress.progress(q_index / len(queries))
            continue

        local_progress = st.progress(0)
        total = len(articles)
        processed = 0

        for batch_start in range(0, total, batch_size):
            batch = articles[batch_start:batch_start + batch_size]
            batch_rows = []

            for article in batch:
                decoded_url = resolve_google_redirect(article["link"])
                batch_rows.append({
                    **article,
                    **q,
                    "decoded_url": decoded_url,
                    "status": "ok" if decoded_url else "failed"
                })

            saved_count = append_rows_immediately(batch_rows)
            total_saved += saved_count

            log_event("batch_saved", {
                "run_id": run_id,
                "batch_size": len(batch_rows),
                "saved": saved_count,
            })

            processed += len(batch_rows)
            local_progress.progress(processed / total)

            if delay > 0:
                time.sleep(delay)

        global_progress.progress(q_index / len(queries))

    log_event("run_completed", {
        "run_id": run_id,
        "queries": len(queries),
        "total_fetched": total_fetched,
        "total_saved": total_saved,
    })

    st.success("🎉 Scraping completed successfully!")
    st.json({
        "run_id": run_id,
        "queries": len(queries),
        "total_fetched": total_fetched,
        "total_saved": total_saved,
    })

# =========================================================
# DATA VIEW
# =========================================================

st.divider()
st.subheader("📚 ESG News Dataset")

stored = load_existing_dataset()
st.write(f"Total stored records: {len(stored)}")

if stored:
    df_all = pd.DataFrame(stored[-300:])
    st.dataframe(df_all, use_container_width=True)

# =========================================================
# LOG VIEWER
# =========================================================

st.divider()
st.subheader("🧾 Scraper Logs")

if LOG_FILE.exists():
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        logs = [json.loads(line) for line in f.readlines()[-200:]]

    log_df = pd.DataFrame(logs)
    st.dataframe(log_df, use_container_width=True)
else:
    st.info("No logs yet.")


# import streamlit as st
# import requests
# import feedparser
# import json
# import time
# from pathlib import Path
# from urllib.parse import quote_plus
# import pandas as pd
# from datetime import datetime
# import uuid

# # =========================================================
# # CONFIG
# # =========================================================

# BASE_DIR = Path(__file__).resolve().parents[1]

# DATA_DIR = BASE_DIR / "data"
# DATA_DIR.mkdir(exist_ok=True)

# LOG_DIR = BASE_DIR / "logs"
# LOG_DIR.mkdir(exist_ok=True)

# DATASET_JSON   = DATA_DIR / "news_dataset_new.json"
# COMPANIES_JSON = DATA_DIR / "esg_companies.json"
# KEYWORDS_JSON  = DATA_DIR / "esg_keywords_flat.json" # "esg_keywords.json"

# LOG_FILE = LOG_DIR / "scraper_runs.jsonl"

# HEADERS = {
#     "User-Agent": "Mozilla/5.0",
#     "Accept": "text/html,application/xhtml+xml",
# }

# REQUEST_TIMEOUT = 20

# # =========================================================
# # LOGGING
# # =========================================================

# def log_event(event_type, payload):
#     record = {
#         "event": event_type,
#         "timestamp": datetime.utcnow().isoformat(),
#         **payload
#     }
#     with open(LOG_FILE, "a", encoding="utf-8") as f:
#         f.write(json.dumps(record, ensure_ascii=False) + "\n")
#     return record

# # =========================================================
# # LOADERS
# # =========================================================

# def load_json(path, default):
#     if path.exists():
#         try:
#             with open(path, "r", encoding="utf-8") as f:
#                 return json.load(f)
#         except Exception:
#             return default
#     return default


# def load_companies():
#     return load_json(COMPANIES_JSON, [])


# def load_keywords():
#     return load_json(KEYWORDS_JSON, {})

# # =========================================================
# # STORAGE
# # =========================================================

# def load_existing_dataset():
#     return load_json(DATASET_JSON, [])


# def save_dataset(new_rows):
#     """
#     Merge new rows into dataset with deduplication (decoded_url).
#     """
#     existing = load_existing_dataset()

#     seen = {
#         row.get("decoded_url")
#         for row in existing
#         if row.get("decoded_url")
#     }

#     clean_new = [
#         row for row in new_rows
#         if row.get("decoded_url") and row.get("decoded_url") not in seen
#     ]

#     combined = existing + clean_new

#     with open(DATASET_JSON, "w", encoding="utf-8") as f:
#         json.dump(combined, f, indent=2, ensure_ascii=False)

#     return clean_new, combined

# def append_rows_immediately(rows):
#     if not rows:
#         return 0
#     new_rows, _ = save_dataset(rows)
#     return len(new_rows)

# # =========================================================
# # HELPERS
# # =========================================================

# def parse_published_date(raw_date):
#     try:
#         return pd.to_datetime(raw_date, utc=True)
#     except Exception:
#         return pd.NaT


# def build_search_rss(query, language, country):
#     encoded_query = quote_plus(query)
#     return (
#         f"https://news.google.com/rss/search?"
#         f"q={encoded_query}&hl={language}&gl={country}&ceid={country}:{language}"
#     )


# def resolve_google_redirect(url):
#     try:
#         r = requests.get(
#             url,
#             headers=HEADERS,
#             timeout=REQUEST_TIMEOUT,
#             allow_redirects=True
#         )
#         return r.url
#     except Exception as e:
#         log_event("redirect_error", {"url": url, "error": str(e)})
#         return None

# # =========================================================
# # QUERY GENERATION
# # =========================================================

# def build_queries(selected_companies, companies, keywords):
#     queries = []
#     for company in companies:
#         if company["code"] not in selected_companies:
#             continue

#         code = company["code"]
#         name = company["company_name"]
#         esg_score = company.get("esg_score")

#         kws = keywords.get(code, [])
#         for kw in kws:
#             queries.append({
#                 "company_code": code,
#                 "company_name": name,
#                 "esg_score": esg_score,
#                 "keyword": kw,
#                 "query": kw
#             })

#     return queries

# # =========================================================
# # FETCHER WITH DATE FILTERING
# # =========================================================

# def fetch_articles_from_query(
#     query,
#     language,
#     country,
#     limit,
#     date_from,
#     date_to,
# ):
#     rss_url = build_search_rss(query, language, country)
#     feed = feedparser.parse(rss_url)

#     rows = []

#     date_from = pd.to_datetime(date_from, utc=True)
#     date_to   = pd.to_datetime(date_to, utc=True) + pd.Timedelta(days=1)

#     for entry in feed.entries[:limit]:
#         published_raw = entry.get("published")
#         published_dt = parse_published_date(published_raw)

#         if pd.isna(published_dt):
#             continue

#         # Date filter
#         if not (date_from <= published_dt <= date_to):
#             if published_dt < date_from:
#                 break
#             continue

#         rows.append({
#             "query": query,
#             "title": entry.get("title"),
#             "link": entry.get("link"),
#             "published": published_dt.isoformat(),
#             "summary": entry.get("summary"),
#             "source": entry.get("source", {}).get("title"),
#             "rss_url": rss_url,
#         })

#     return rows

# # =========================================================
# # STREAMLIT UI
# # =========================================================

# st.set_page_config(layout="wide")
# st.title("🌱 ESG Company → Keyword → News Scraper")
# st.caption("Date-filtered • Incremental • Logged • Reproducible")

# # ---------------- Sidebar Controls ----------------

# with st.sidebar:
#     st.header("🏢 Company Selection")

#     companies = load_companies()
#     keywords = load_keywords()

#     if not companies:
#         st.error("Missing data/esg_companies.json")
#         st.stop()

#     company_map = {
#         f"{c['code']} — {c['company_name']}": c["code"]
#         for c in companies
#     }

#     selected_labels = st.multiselect(
#         "Select companies",
#         list(company_map.keys()),
#         default=list(company_map.keys())[:2]
#     )

#     selected_codes = [company_map[label] for label in selected_labels]

#     st.divider()
#     st.header("⚙️ Scraping Settings")

#     col1, col2 = st.columns(2)
#     with col1:
#         language = st.selectbox("Language", ["en", "id", "it"], index=0)
#     with col2:
#         country = st.selectbox("Country", ["US", "ID", "IT"], index=0)

#     limit = st.slider("Articles per keyword", 1, 100, 20)
#     batch_size = st.slider("Batch size", 1, 10, 5)
#     delay = st.slider("Delay between batches (seconds)", 0.0, 3.0, 1.0)

#     st.divider()
#     st.header("📅 Date Filter")

#     date_from = st.date_input("From date")
#     date_to   = st.date_input("To date")

#     run_btn = st.button("🚀 Run Company Scraping")

# # =========================================================
# # RUN PIPELINE
# # =========================================================

# if run_btn:
#     run_id = str(uuid.uuid4())

#     run_params = {
#         "run_id": run_id,
#         "companies": selected_codes,
#         "language": language,
#         "country": country,
#         "limit": limit,
#         "batch_size": batch_size,
#         "delay": delay,
#         "date_from": str(date_from),
#         "date_to": str(date_to),
#     }

#     log_event("run_started", run_params)

#     if date_from > date_to:
#         st.error("❌ From date must be earlier than To date.")
#         log_event("run_failed", {"run_id": run_id, "reason": "invalid_date_range"})
#         st.stop()

#     queries = build_queries(
#         selected_companies=selected_codes,
#         companies=companies,
#         keywords=keywords
#     )

#     if not queries:
#         st.warning("No keywords found for selected companies.")
#         log_event("run_failed", {"run_id": run_id, "reason": "no_queries"})
#         st.stop()

#     st.success(f"Generated {len(queries)} keyword queries")

#     global_progress = st.progress(0)
#     total_saved = 0
#     total_fetched = 0

#     for q_index, q in enumerate(queries, start=1):
#         st.subheader(f"🔎 {q['company_name']} → {q['keyword']}")

#         articles = fetch_articles_from_query(
#             query=q["query"],
#             language=language,
#             country=country,
#             limit=limit,
#             date_from=date_from,
#             date_to=date_to,
#         )

#         fetched_count = len(articles)
#         total_fetched += fetched_count

#         log_event("query_fetched", {
#             "run_id": run_id,
#             "company_code": q["company_code"],
#             "keyword": q["keyword"],
#             "fetched": fetched_count,
#         })

#         if not articles:
#             st.warning("No articles found in date range.")
#             global_progress.progress(q_index / len(queries))
#             continue

#         local_progress = st.progress(0)
#         total = len(articles)
#         processed = 0

#         for batch_start in range(0, total, batch_size):
#             batch = articles[batch_start:batch_start + batch_size]
#             batch_rows = []

#             for article in batch:
#                 decoded_url = resolve_google_redirect(article["link"])

#                 row = {
#                     **article,
#                     **q,
#                     "decoded_url": decoded_url,
#                     "status": "ok" if decoded_url else "failed"
#                 }

#                 batch_rows.append(row)

#             saved_count = append_rows_immediately(batch_rows)
#             total_saved += saved_count

#             log_event("batch_saved", {
#                 "run_id": run_id,
#                 "batch_size": len(batch_rows),
#                 "saved": saved_count,
#             })

#             processed += len(batch_rows)
#             local_progress.progress(processed / total)

#             if delay > 0:
#                 time.sleep(delay)

#         global_progress.progress(q_index / len(queries))

#     summary = {
#         "run_id": run_id,
#         "queries": len(queries),
#         "total_fetched": total_fetched,
#         "total_saved": total_saved,
#     }

#     log_event("run_completed", summary)
#     st.success("🎉 Scraping completed successfully!")
#     st.json(summary)

# # =========================================================
# # STORED DATA VIEW
# # =========================================================

# st.divider()
# st.subheader("📚 ESG News Dataset")

# stored = load_existing_dataset()
# st.write(f"Total stored records: {len(stored)}")

# if stored:
#     df_all = pd.DataFrame(stored[-300:])
#     st.dataframe(df_all, use_container_width=True)

#     st.download_button(
#         "⬇️ Download Dataset JSON",
#         json.dumps(stored, indent=2, ensure_ascii=False),
#         file_name="news_dataset.json",
#         mime="application/json"
#     )

# # =========================================================
# # LOG VIEWER
# # =========================================================

# st.divider()
# st.subheader("🧾 Scraper Logs")

# if LOG_FILE.exists():
#     with open(LOG_FILE, "r", encoding="utf-8") as f:
#         logs = [json.loads(line) for line in f.readlines()[-200:]]

#     log_df = pd.DataFrame(logs)
#     st.dataframe(log_df, use_container_width=True)

#     st.download_button(
#         "⬇️ Download Logs",
#         json.dumps(logs, indent=2),
#         file_name="scraper_logs.json",
#         mime="application/json"
#     )
# else:
#     st.info("No logs yet.")


# import streamlit as st
# import requests
# import feedparser
# import json
# import time
# from pathlib import Path
# from urllib.parse import quote_plus
# import pandas as pd

# # =========================================================
# # CONFIG
# # =========================================================

# DATA_DIR = Path("data")
# DATA_DIR.mkdir(exist_ok=True)

# DATASET_JSON   = DATA_DIR / "news_dataset.json"
# COMPANIES_JSON = DATA_DIR / "esg_companies.json"
# KEYWORDS_JSON  = DATA_DIR / "esg_keywords.json"

# HEADERS = {
#     "User-Agent": "Mozilla/5.0",
#     "Accept": "text/html,application/xhtml+xml",
# }

# REQUEST_TIMEOUT = 20

# # =========================================================
# # LOADERS
# # =========================================================

# def load_json(path, default):
#     if path.exists():
#         try:
#             with open(path, "r", encoding="utf-8") as f:
#                 return json.load(f)
#         except Exception:
#             return default
#     return default


# def load_companies():
#     return load_json(COMPANIES_JSON, [])


# def load_keywords():
#     return load_json(KEYWORDS_JSON, {})

# # =========================================================
# # STORAGE
# # =========================================================

# def load_existing_dataset():
#     return load_json(DATASET_JSON, [])


# def save_dataset(new_rows):
#     """
#     Merge new rows into dataset with deduplication (decoded_url).
#     """
#     existing = load_existing_dataset()

#     seen = {
#         row.get("decoded_url")
#         for row in existing
#         if row.get("decoded_url")
#     }

#     clean_new = [
#         row for row in new_rows
#         if row.get("decoded_url") and row.get("decoded_url") not in seen
#     ]

#     combined = existing + clean_new

#     with open(DATASET_JSON, "w", encoding="utf-8") as f:
#         json.dump(combined, f, indent=2, ensure_ascii=False)

#     return clean_new, combined


# def append_rows_immediately(rows):
#     if not rows:
#         return 0
#     new_rows, _ = save_dataset(rows)
#     return len(new_rows)

# # =========================================================
# # HELPERS
# # =========================================================

# def parse_published_date(raw_date):
#     """
#     Normalize RSS published date into pandas Timestamp.
#     """
#     try:
#         return pd.to_datetime(raw_date, utc=True)
#     except Exception:
#         return pd.NaT


# def build_search_rss(query, language, country):
#     encoded_query = quote_plus(query)
#     return (
#         f"https://news.google.com/rss/search?"
#         f"q={encoded_query}&hl={language}&gl={country}&ceid={country}:{language}"
#     )


# def resolve_google_redirect(url):
#     try:
#         r = requests.get(
#             url,
#             headers=HEADERS,
#             timeout=REQUEST_TIMEOUT,
#             allow_redirects=True
#         )
#         return r.url
#     except Exception:
#         return None

# # =========================================================
# # QUERY GENERATION
# # =========================================================

# def build_queries(selected_companies, companies, keywords):
#     """
#     Company → keyword → query expansion
#     """
#     queries = []

#     for company in companies:
#         if company["code"] not in selected_companies:
#             continue

#         code = company["code"]
#         name = company["company_name"]
#         esg_score = company.get("esg_score")

#         kws = keywords.get(code, [])

#         for kw in kws:
#             queries.append({
#                 "company_code": code,
#                 "company_name": name,
#                 "esg_score": esg_score,
#                 "keyword": kw,
#                 "query": kw
#             })

#     return queries

# # =========================================================
# # FETCHER WITH DATE FILTERING
# # =========================================================

# def fetch_articles_from_query(
#     query,
#     language,
#     country,
#     limit,
#     date_from,
#     date_to,
# ):
#     rss_url = build_search_rss(query, language, country)
#     feed = feedparser.parse(rss_url)

#     rows = []

#     date_from = pd.to_datetime(date_from, utc=True)
#     date_to   = pd.to_datetime(date_to, utc=True) + pd.Timedelta(days=1)

#     for entry in feed.entries[:limit]:
#         published_raw = entry.get("published")
#         published_dt = parse_published_date(published_raw)

#         if pd.isna(published_dt):
#             continue

#         # Date filter
#         if not (date_from <= published_dt <= date_to):
#             # Early stop if older than range
#             if published_dt < date_from:
#                 break
#             continue

#         rows.append({
#             "query": query,
#             "title": entry.get("title"),
#             "link": entry.get("link"),
#             "published": published_dt.isoformat(),
#             "summary": entry.get("summary"),
#             "source": entry.get("source", {}).get("title"),
#             "rss_url": rss_url,
#         })

#     return rows

# # =========================================================
# # STREAMLIT UI
# # =========================================================

# st.set_page_config(layout="wide")
# st.title("🌱 ESG Company → Keyword → News Scraper")
# st.caption("Date-filtered, incremental, crash-safe ESG news harvesting")

# # ---------------- Sidebar Controls ----------------

# with st.sidebar:
#     st.header("🏢 Company Selection")

#     companies = load_companies()
#     keywords = load_keywords()

#     if not companies:
#         st.error("Missing data/esg_companies.json")
#         st.stop()

#     company_map = {
#         f"{c['code']} — {c['company_name']}": c["code"]
#         for c in companies
#     }

#     selected_labels = st.multiselect(
#         "Select companies",
#         list(company_map.keys()),
#         default=list(company_map.keys())[:2]
#     )

#     selected_codes = [company_map[label] for label in selected_labels]

#     st.divider()
#     st.header("⚙️ Scraping Settings")

#     col1, col2 = st.columns(2)
#     with col1:
#         language = st.selectbox("Language", ["en", "id", "it"], index=0)
#     with col2:
#         country = st.selectbox("Country", ["US", "ID", "IT"], index=0)

#     limit = st.slider("Articles per keyword", 1, 100, 20)
#     batch_size = st.slider("Batch size", 1, 10, 5)
#     delay = st.slider("Delay between batches (seconds)", 0.0, 3.0, 1.0)

#     st.divider()
#     st.header("📅 Date Filter")

#     date_from = st.date_input("From date")
#     date_to   = st.date_input("To date")

#     run_btn = st.button("🚀 Run Company Scraping")

# # =========================================================
# # RUN PIPELINE
# # =========================================================

# if run_btn:
#     companies_data = load_companies()
#     keywords_data = load_keywords()

#     queries = build_queries(
#         selected_companies=selected_codes,
#         companies=companies_data,
#         keywords=keywords_data
#     )

#     if not queries:
#         st.warning("No keywords found for selected companies.")
#         st.stop()

#     if date_from > date_to:
#         st.error("❌ From date must be earlier than To date.")
#         st.stop()

#     st.success(f"Generated {len(queries)} keyword queries")

#     global_progress = st.progress(0)
#     total_saved = 0

#     for q_index, q in enumerate(queries, start=1):
#         st.subheader(f"🔎 {q['company_name']} → {q['keyword']}")

#         articles = fetch_articles_from_query(
#             query=q["query"],
#             language=language,
#             country=country,
#             limit=limit,
#             date_from=date_from,
#             date_to=date_to,
#         )

#         if not articles:
#             st.warning("No articles found in date range.")
#             global_progress.progress(q_index / len(queries))
#             continue

#         local_progress = st.progress(0)
#         total = len(articles)
#         processed = 0

#         for batch_start in range(0, total, batch_size):
#             batch = articles[batch_start:batch_start + batch_size]
#             batch_rows = []

#             for article in batch:
#                 decoded_url = resolve_google_redirect(article["link"])

#                 row = {
#                     **article,
#                     **q,
#                     "decoded_url": decoded_url,
#                     "status": "ok" if decoded_url else "failed"
#                 }

#                 batch_rows.append(row)

#             # Save immediately
#             saved_count = append_rows_immediately(batch_rows)
#             total_saved += saved_count

#             processed += len(batch_rows)
#             local_progress.progress(processed / total)

#             if delay > 0:
#                 time.sleep(delay)

#         st.success(f"💾 Saved so far: {total_saved} new records")
#         global_progress.progress(q_index / len(queries))

#     st.success("🎉 Scraping completed successfully!")

# # =========================================================
# # STORED DATA VIEW
# # =========================================================

# st.divider()
# st.subheader("📚 ESG News Dataset")

# stored = load_existing_dataset()
# st.write(f"Total stored records: {len(stored)}")

# if stored:
#     df_all = pd.DataFrame(stored[-300:])   # latest 300 only
#     st.dataframe(df_all, use_container_width=True)

#     st.download_button(
#         "⬇️ Download Dataset JSON",
#         json.dumps(stored, indent=2, ensure_ascii=False),
#         file_name="news_dataset.json",
#         mime="application/json"
#     )

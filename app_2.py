import streamlit as st
import trafilatura
import requests
import pandas as pd
import json
import os
from datetime import datetime
from urllib.parse import urlparse

# =====================================================
# CONFIG
# =====================================================
DATA_DIR = "data"
ARTICLE_DIR = os.path.join(DATA_DIR, "articles")
LOG_DIR = os.path.join(DATA_DIR, "logs")

BATCH_SIZE = 50

INVALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".mp4")

os.makedirs(ARTICLE_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# =====================================================
# HELPERS
# =====================================================
def is_valid_article_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    path = urlparse(url).path.lower()
    return url.startswith("http") and not path.endswith(INVALID_EXTENSIONS)


def extract_article_text(url: str):
    try:
        response = requests.get(
            url,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        response.raise_for_status()
    except Exception as e:
        return None, str(e)

    text = trafilatura.extract(
        response.text,
        include_comments=False,
        include_tables=False
    )

    if not text or len(text.strip()) < 200:
        return None, "Extraction failed or text too short"

    return text, None


def load_existing_urls():
    """Load URLs already scraped across all article JSON files"""
    urls = set()

    for fname in os.listdir(ARTICLE_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(ARTICLE_DIR, fname), "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    if "url" in item:
                        urls.add(item["url"])
        except Exception:
            continue

    return urls


def append_json(path, new_items):
    """Append list items to a JSON list safely"""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
    else:
        data = []

    data.extend(new_items)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =====================================================
# STREAMLIT SETUP
# =====================================================
st.set_page_config(page_title="📰 Robust News Scraper", layout="wide")
st.title("📰 Robust News Scraper (Single + Bulk)")
st.caption("Batch-safe, resumable, deduplicated article extraction")

tab_single, tab_bulk = st.tabs(["🔗 Single URL", "📂 Bulk Scraping"])

# =====================================================
# SINGLE URL MODE
# =====================================================
with tab_single:
    st.subheader("🔗 Single Article Scraping")

    url = st.text_input("Article URL")

    if st.button("🚀 Scrape URL"):
        ts = datetime.now().isoformat()

        article_path = os.path.join(
            ARTICLE_DIR, f"articles_{datetime.now().date()}.json"
        )
        log_path = os.path.join(
            LOG_DIR, f"scrape_log_{datetime.now().date()}.json"
        )

        if not is_valid_article_url(url):
            st.error("Invalid article URL (image/pdf/media)")
            append_json(log_path, [{
                "url": url,
                "timestamp": ts,
                "status": "failed",
                "reason": "Invalid URL"
            }])
        else:
            with st.spinner("Scraping article..."):
                text, error = extract_article_text(url)

                if error:
                    st.error(error)
                    append_json(log_path, [{
                        "url": url,
                        "timestamp": ts,
                        "status": "failed",
                        "reason": error
                    }])
                else:
                    article = {
                        "url": url,
                        "fetched_at": ts,
                        "status": "success",
                        "text": text,
                        "text_length": len(text)
                    }

                    append_json(article_path, [article])

                    st.success("✅ Article extracted successfully")
                    st.text_area("Extracted Text", text, height=400)

# =====================================================
# BULK MODE
# =====================================================
with tab_bulk:
    st.subheader("📂 Bulk Scraping")

    input_mode = st.radio(
        "Bulk input method",
        ["Upload CSV", "Paste URL list"],
        horizontal=True
    )

    urls = []

    # -----------------------------
    # CSV INPUT
    # -----------------------------
    if input_mode == "Upload CSV":
        uploaded_file = st.file_uploader(
            "Upload CSV with a column named 'url'",
            type=["csv"]
        )

        if uploaded_file:
            df = pd.read_csv(uploaded_file)

            if "url" not in df.columns:
                st.error("CSV must contain a column named 'url'")
                st.stop()

            urls = (
                df["url"]
                .dropna()
                .astype(str)
                .str.strip()
                .unique()
                .tolist()
            )

    # -----------------------------
    # TEXTAREA INPUT
    # -----------------------------
    else:
        pasted_urls = st.text_area(
            "Paste URLs (one per line)",
            height=220,
            placeholder="https://example.com/article-1\nhttps://example.com/article-2"
        )

        if pasted_urls:
            urls = list({
                line.strip()
                for line in pasted_urls.splitlines()
                if line.strip()
            })

    # -----------------------------
    # RUN BULK SCRAPER (BATCHED)
    # -----------------------------
    if urls:
        st.info(f"📌 {len(urls)} URLs loaded")

        if st.button("🚀 Start Bulk Scraping"):
            existing_urls = load_existing_urls()
            urls_to_process = [u for u in urls if u not in existing_urls]

            st.caption(f"🔁 Deduplication: {len(existing_urls)} URLs already scraped")
            st.info(f"🚀 Processing {len(urls_to_process)} new URLs")

            if not urls_to_process:
                st.success("All URLs already scraped 🎉")
                st.stop()

            article_path = os.path.join(
                ARTICLE_DIR, f"articles_{datetime.now().date()}.json"
            )
            log_path = os.path.join(
                LOG_DIR, f"scrape_log_{datetime.now().date()}.json"
            )

            progress = st.progress(0)
            total = len(urls_to_process)
            processed = 0

            for batch_start in range(0, total, BATCH_SIZE):
                batch = urls_to_process[batch_start:batch_start + BATCH_SIZE]

                batch_articles = []
                batch_logs = []

                for url in batch:
                    ts = datetime.now().isoformat()

                    if not is_valid_article_url(url):
                        batch_logs.append({
                            "url": url,
                            "timestamp": ts,
                            "status": "failed",
                            "reason": "Invalid URL (image/pdf/media)"
                        })
                        continue

                    text, error = extract_article_text(url)

                    if error:
                        batch_logs.append({
                            "url": url,
                            "timestamp": ts,
                            "status": "failed",
                            "reason": error
                        })
                    else:
                        batch_articles.append({
                            "url": url,
                            "fetched_at": ts,
                            "status": "success",
                            "text": text,
                            "text_length": len(text)
                        })

                    processed += 1
                    progress.progress(processed / total)

                # 🔐 Incremental save after each batch
                if batch_articles:
                    append_json(article_path, batch_articles)

                if batch_logs:
                    append_json(log_path, batch_logs)

                st.write(
                    f"✅ Batch {batch_start // BATCH_SIZE + 1} "
                    f"processed ({len(batch)} URLs)"
                )

            st.success("🎉 Bulk scraping completed safely")
            st.metric("Total processed", processed)


# import streamlit as st
# import trafilatura
# import requests
# import pandas as pd
# import json
# import os
# from datetime import datetime
# from urllib.parse import urlparse

# # =====================================================
# # Config
# # =====================================================
# DATA_DIR = "data"
# ARTICLE_DIR = os.path.join(DATA_DIR, "articles")
# LOG_DIR = os.path.join(DATA_DIR, "logs")

# os.makedirs(ARTICLE_DIR, exist_ok=True)
# os.makedirs(LOG_DIR, exist_ok=True)

# INVALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".mp4")

# # =====================================================
# # Helpers
# # =====================================================
# def is_valid_article_url(url: str) -> bool:
#     path = urlparse(url).path.lower()
#     return url.startswith("http") and not path.endswith(INVALID_EXTENSIONS)


# def extract_article_text(url: str):
#     try:
#         response = requests.get(
#             url,
#             timeout=10,
#             headers={"User-Agent": "Mozilla/5.0"}
#         )
#         response.raise_for_status()
#     except Exception as e:
#         return None, str(e)

#     text = trafilatura.extract(
#         response.text,
#         include_comments=False,
#         include_tables=False
#     )

#     if not text or len(text.strip()) < 200:
#         return None, "Extraction failed or text too short"

#     return text, None


# def save_json(path, data):
#     with open(path, "w", encoding="utf-8") as f:
#         json.dump(data, f, ensure_ascii=False, indent=2)

# # =====================================================
# # Streamlit Setup
# # =====================================================
# st.set_page_config(page_title="📰 Bulk News Scraper", layout="wide")
# st.title("📰 News Article Scraper (Single + Bulk)")
# st.caption("Extract article text, save JSON output, and log failures")

# # =====================================================
# # Input Section
# # =====================================================
# tab_single, tab_bulk = st.tabs(["🔗 Single URL", "📂 Bulk CSV Upload"])

# # =====================================================
# # SINGLE URL MODE
# # =====================================================
# with tab_single:
#     url = st.text_input("Article URL")

#     if st.button("🚀 Scrape URL"):
#         logs = []
#         articles = []

#         ts = datetime.now().isoformat()

#         if not is_valid_article_url(url):
#             st.error("Invalid article URL (image, pdf, or unsupported)")
#             logs.append({
#                 "url": url,
#                 "timestamp": ts,
#                 "status": "failed",
#                 "reason": "Invalid URL"
#             })
#         else:
#             with st.spinner("Scraping article..."):
#                 text, error = extract_article_text(url)

#                 if error:
#                     st.error(error)
#                     logs.append({
#                         "url": url,
#                         "timestamp": ts,
#                         "status": "failed",
#                         "reason": error
#                     })
#                 else:
#                     articles.append({
#                         "url": url,
#                         "fetched_at": ts,
#                         "status": "success",
#                         "text": text,
#                         "text_length": len(text)
#                     })
#                     st.success("Article extracted successfully")
#                     st.text_area("Extracted Text", text, height=400)

#         # Save outputs
#         if articles:
#             save_json(
#                 os.path.join(ARTICLE_DIR, f"articles_{datetime.now().date()}.json"),
#                 articles
#             )

#         if logs:
#             save_json(
#                 os.path.join(LOG_DIR, f"scrape_log_{datetime.now().date()}.json"),
#                 logs
#             )

# # =====================================================
# # BULK MODE
# # =====================================================
# with tab_bulk:
#     st.subheader("📂 Bulk Scraping")

#     input_mode = st.radio(
#         "Bulk input method",
#         ["Upload CSV", "Paste URL list"],
#         horizontal=True
#     )

#     urls = []

#     # -----------------------------
#     # CSV Upload
#     # -----------------------------
#     if input_mode == "Upload CSV":
#         uploaded_file = st.file_uploader(
#             "Upload CSV with a column named 'url'",
#             type=["csv"]
#         )

#         if uploaded_file:
#             df = pd.read_csv(uploaded_file)

#             if "url" not in df.columns:
#                 st.error("CSV must contain a column named 'url'")
#                 st.stop()

#             urls = (
#                 df["url"]
#                 .dropna()
#                 .astype(str)
#                 .str.strip()
#                 .unique()
#                 .tolist()
#             )

#     # -----------------------------
#     # Paste URLs
#     # -----------------------------
#     else:
#         pasted_urls = st.text_area(
#             "Paste URLs (one per line)",
#             height=220,
#             placeholder="https://example.com/article-1\nhttps://example.com/article-2"
#         )

#         if pasted_urls:
#             urls = list({
#                 line.strip()
#                 for line in pasted_urls.splitlines()
#                 if line.strip()
#             })

#     # -----------------------------
#     # Run Bulk Scraper
#     # -----------------------------
#     if urls:
#         st.info(f"📌 {len(urls)} unique URLs loaded")

#         if st.button("🚀 Start Bulk Scraping"):
#             articles = []
#             logs = []

#             ts = datetime.now().isoformat()
#             progress = st.progress(0)

#             for i, url in enumerate(urls):
#                 progress.progress((i + 1) / len(urls))

#                 if not is_valid_article_url(url):
#                     logs.append({
#                         "url": url,
#                         "timestamp": ts,
#                         "status": "failed",
#                         "reason": "Invalid URL (image/pdf/media)"
#                     })
#                     continue

#                 text, error = extract_article_text(url)

#                 if error:
#                     logs.append({
#                         "url": url,
#                         "timestamp": ts,
#                         "status": "failed",
#                         "reason": error
#                     })
#                 else:
#                     articles.append({
#                         "url": url,
#                         "fetched_at": ts,
#                         "status": "success",
#                         "text": text,
#                         "text_length": len(text)
#                     })

#             # -----------------------------
#             # Save outputs
#             # -----------------------------
#             article_path = os.path.join(
#                 ARTICLE_DIR,
#                 f"articles_{datetime.now().date()}.json"
#             )
#             log_path = os.path.join(
#                 LOG_DIR,
#                 f"scrape_log_{datetime.now().date()}.json"
#             )

#             save_json(article_path, articles)
#             save_json(log_path, logs)

#             st.success("✅ Bulk scraping completed")
#             st.markdown(f"**Articles saved:** `{article_path}`")
#             st.markdown(f"**Logs saved:** `{log_path}`")

#             st.metric("Success", len(articles))
#             st.metric("Failed", len(logs))

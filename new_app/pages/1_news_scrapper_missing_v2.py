# pages/News_Extractor.py

import streamlit as st
import json
import pandas as pd
import re
import requests
import os
from bs4 import BeautifulSoup
from datetime import datetime
from googlenewsdecoder import new_decoderv1  # ← Add this import

st.set_page_config(page_title="News Extractor", layout="wide")

st.title("📰 ESG News Extractor")

# -----------------------------
# Load Data
# -----------------------------
@st.cache_data
def load_data():
    with open("data/news_dataset_new.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return pd.DataFrame(data)

df = load_data()

# -----------------------------
# Clean HTML from summary
# -----------------------------
def clean_html(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ").strip()

df["clean_summary"] = df["summary"].apply(clean_html)

# Convert published date
df["published"] = pd.to_datetime(df["published"], errors="coerce")

# -----------------------------
# Load Already Scraped Content
# -----------------------------
SCRAPED_FILE = "data/news_content.json"

def load_scraped():
    if os.path.exists(SCRAPED_FILE):
        with open(SCRAPED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_scraped(scraped_dict):
    os.makedirs("data", exist_ok=True)
    with open(SCRAPED_FILE, "w", encoding="utf-8") as f:
        json.dump(scraped_dict, f, ensure_ascii=False, indent=2)

# -----------------------------
# Scrape Article Content
# -----------------------------
def resolve_google_news_url(url: str) -> str:
    """
    Decode Google News RSS URL to get the actual article URL.
    Uses googlenewsdecoder to bypass JS-based redirects.
    """
    try:
        # Only decode if it's a Google News URL
        if "news.google.com" in url:
            result = new_decoderv1(url)
            if result and result.get("status") == True:
                return result["decoded_url"]
        return url
    except Exception as e:
        return url  # Fallback to original

def scrape_article(url: str) -> tuple[str, str]:
    """
    Returns (content, resolved_url)
    Steps:
      1. Decode Google News URL → real article URL
      2. Scrape the real article page
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    # Step 1: Decode Google News URL to real URL
    resolved_url = resolve_google_news_url(url)

    # Step 2: Scrape the resolved URL
    try:
        response = requests.get(resolved_url, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove noisy tags
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # Try common article content selectors
        for selector in [
            "article",
            "main",
            "[class*='article-body']",
            "[class*='post-content']",
            "[class*='entry-content']",
            "[class*='story-body']",
            "[class*='content-body']",
            "[itemprop='articleBody']",
        ]:
            content = soup.select_one(selector)
            if content:
                text = content.get_text(separator="\n").strip()
                if len(text) > 200:  # Ensure it's meaningful content
                    return text, resolved_url

        # Fallback to body text
        body_text = soup.body.get_text(separator="\n").strip() if soup.body else "No content found."
        return body_text, resolved_url

    except Exception as e:
        return f"[Error scraping: {str(e)}]", resolved_url

# -----------------------------
# Sidebar Filters
# -----------------------------
st.sidebar.header("Filter Options")

# Load scraped_data early so we can filter companies by "0 missing"
scraped_data = load_scraped()

# compute list of companies that have all their filtered links already scraped
all_companies = sorted(df["company_name"].dropna().unique().tolist())
missing_counts = {}
companies_with_missing = []
companies_with_complete = []
for comp in all_companies:
    comp_links = df[df["company_name"] == comp]["link"].dropna().unique().tolist()
    missing_for_comp = [l for l in comp_links if l not in scraped_data]
    missing_counts[comp] = len(missing_for_comp)
    if missing_counts[comp] > 0:
        companies_with_missing.append(comp)
    else:
        companies_with_complete.append(comp)

# If there are companies with missing articles, show them by default so user can scrape non-zero missing.
if companies_with_missing:
    company_options = ["All"] + companies_with_missing
    st.sidebar.info(f"{len(companies_with_missing)} companies have missing articles — showing those by default.")
else:
    # all companies fully scraped (or no data) — show all companies
    company_options = ["All"] + all_companies
    st.sidebar.success("All companies have fully scraped content; showing all companies.")

company_filter = st.sidebar.selectbox(
    "Select Company",
    company_options
)

keyword_filter = st.sidebar.selectbox(
    "Select Keyword",
    ["All"] + sorted(df["keyword"].dropna().unique().tolist())
)

date_range = st.sidebar.date_input(
    "Select Date Range",
    []
)

filtered_df = df.copy()

if company_filter != "All":
    filtered_df = filtered_df[filtered_df["company_name"] == company_filter]

if keyword_filter != "All":
    filtered_df = filtered_df[filtered_df["keyword"] == keyword_filter]

if len(date_range) == 2:
    filtered_df = filtered_df[
        (filtered_df["published"].dt.date >= date_range[0]) &
        (filtered_df["published"].dt.date <= date_range[1])
    ]

st.subheader(f"Found {len(filtered_df)} Articles")

# -----------------------------
# Scraping Section
# -----------------------------
st.markdown("---")
st.subheader("🔍 Scrape News Content")

scraped_data = load_scraped()

# Identify scraped vs missing
all_links = filtered_df["link"].dropna().tolist()
scraped_links = set(scraped_data.keys())
missing_links = [link for link in all_links if link not in scraped_links]
already_scraped = [link for link in all_links if link in scraped_links]

col1, col2, col3 = st.columns(3)
col1.metric("📰 Total Articles (Filtered)", len(all_links))
col2.metric("✅ Already Scraped", len(already_scraped))
col3.metric("❌ Missing / Not Scraped", len(missing_links))

st.markdown("#### Scraping Options")

scrape_mode = st.radio(
    "Choose what to scrape:",
    ["Only Missing Articles", "All Filtered Articles (Overwrite)"],
    horizontal=True
)

links_to_scrape = missing_links if scrape_mode == "Only Missing Articles" else all_links

max_scrape = st.slider(
    f"How many articles to scrape? (Available: {len(links_to_scrape)})",
    min_value=1,
    max_value=max(len(links_to_scrape), 1),
    value=min(10, max(len(links_to_scrape), 1)),
    disabled=len(links_to_scrape) == 0
)

if len(links_to_scrape) == 0:
    st.success("✅ All filtered articles have already been scraped!")
else:
    st.info(f"Will scrape **{max_scrape}** out of **{len(links_to_scrape)}** articles.")

    if st.button("🚀 Start Scraping"):
        selected_links = links_to_scrape[:max_scrape]
        progress_bar = st.progress(0)
        status_text = st.empty()
        results_log = []

        for i, link in enumerate(selected_links):
            status_text.text(f"Scraping ({i+1}/{len(selected_links)}): {link[:80]}...")
            content, resolved_url = scrape_article(link)  # ← unpack tuple

            # Find matching row metadata
            row = filtered_df[filtered_df["link"] == link].iloc[0]
            scraped_data[link] = {
                "title": row.get("title", ""),
                "company_name": row.get("company_name", ""),
                "company_code": row.get("company_code", ""),
                "keyword": row.get("keyword", ""),
                "published": str(row.get("published", "")),
                "source": row.get("source", ""),
                "link": link,
                "resolved_url": resolved_url,  # ← store actual article URL
                "content": content,
                "scraped_at": datetime.now().isoformat()
            }

            is_error = content.startswith("[Error")
            results_log.append({
                "original_link": link[:60],
                "resolved_url": resolved_url[:80],
                "status": "❌ Error" if is_error else "✅ Success",
                "preview": content[:100]
            })

            progress_bar.progress((i + 1) / len(selected_links))

        save_scraped(scraped_data)
        status_text.text("✅ Scraping complete!")

        st.success(f"Saved {len(selected_links)} articles to `{SCRAPED_FILE}`")

        # Show result log
        st.markdown("#### Scraping Results")
        results_df = pd.DataFrame(results_log)
        st.dataframe(results_df, use_container_width=True)

        st.cache_data.clear()

# -----------------------------
# Missing Articles Table
# -----------------------------
if missing_links:
    with st.expander(f"📋 View {len(missing_links)} Missing Articles"):
        missing_df = filtered_df[filtered_df["link"].isin(missing_links)][
            ["title", "company_name", "keyword", "published", "link"]
        ]
        st.dataframe(missing_df.reset_index(drop=True), use_container_width=True)

# -----------------------------
# Display Articles
# -----------------------------
st.markdown("---")
st.subheader("📄 Articles")

for idx, row in filtered_df.iterrows():
    with st.container():
        st.markdown(f"### {row['title']}")
        st.markdown(f"**Source:** {row['source']}")
        st.markdown(f"**Published:** {row['published']}")
        st.markdown(f"**Company:** {row['company_name']} ({row['company_code']})")
        st.markdown(f"**ESG Score:** {row['esg_score']}")

        # Show scraped badge
        if row["link"] in scraped_data:
            st.success("✅ Content Scraped")
        else:
            st.warning("⏳ Not Yet Scraped")

        st.markdown("---")
        st.write(row["clean_summary"])
        st.markdown(f"[Read Full Article]({row['link']})")
        st.divider()

# -----------------------------
# Export Button
# -----------------------------
st.download_button(
    label="Download Filtered Data as CSV",
    data=filtered_df.to_csv(index=False),
    file_name="filtered_news.csv",
    mime="text/csv"
)
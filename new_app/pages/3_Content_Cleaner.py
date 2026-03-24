# pages/Content_Cleaner.py

import streamlit as st
import json
import pandas as pd
import os
import re

st.set_page_config(page_title="Content Cleaner", layout="wide")
st.title("🧹 News Content Cleaner")

# -----------------------------
# File Paths
# -----------------------------
SCRAPED_FILE = "data/news_content.json"
CLEANED_FILE = "data/extra_text.json"
NOISE_PHRASES_FILE = "data/noise_phrases.json"

# -----------------------------
# Default Noise Phrases
# -----------------------------
DEFAULT_NOISE_PHRASES = [
    "Kelola preferensi cookie",
    "Manage cookie preferences",
    "Cookie Settings",
    "Accept all cookies",
    "Privacy Policy",
    "Terms of Service",
    "Subscribe to our newsletter",
    "Sign up for our newsletter",
    "All rights reserved",
    "Advertisement",
    "ADVERTISEMENT",
    "Read more:",
    "Also read:",
    "Share this article",
    "Follow us on",
    "Click here to",
    "Download our app",
    "Enable JavaScript",
    "JavaScript is required",
    "Your browser does not support",
    "Please enable cookies",
    "We use cookies",
    "By continuing to browse",
    "© Copyright",
    "Loading...",
    "Skip to content",
    "Back to top",
]

# -----------------------------
# Load / Save Noise Phrases
# -----------------------------
def load_noise_phrases():
    if os.path.exists(NOISE_PHRASES_FILE):
        with open(NOISE_PHRASES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_NOISE_PHRASES

def save_noise_phrases(phrases: list):
    os.makedirs("data", exist_ok=True)
    with open(NOISE_PHRASES_FILE, "w", encoding="utf-8") as f:
        json.dump(phrases, f, ensure_ascii=False, indent=2)

# -----------------------------
# Load Scraped Content
# -----------------------------
@st.cache_data
def load_scraped():
    if os.path.exists(SCRAPED_FILE):
        with open(SCRAPED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

@st.cache_data
def load_cleaned():
    if os.path.exists(CLEANED_FILE):
        with open(CLEANED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

scraped_data = load_scraped()
cleaned_data = load_cleaned()

if not scraped_data:
    st.error("❌ No scraped data found in `data/news_content.json`. Please run the News Extractor first.")
    st.stop()

# -----------------------------
# Clean Content Function
# -----------------------------
def is_byline(line: str) -> bool:
    """
    Detect reporter/editor byline patterns like:
    'Reporter: Arfyana Citra Rahayu | Editor: Wahyu T.Rahmawati'
    """
    byline_keywords = [
        "reporter", "editor", "penulis", "wartawan",
        "kontributor", "author", "written by", "ditulis oleh",
        "redaktur", "jurnalis", "oleh:", "by:"
    ]
    line_lower = line.lower()

    # Must contain at least one byline keyword
    has_keyword = any(kw in line_lower for kw in byline_keywords)

    # Common byline separators
    has_separator = any(sep in line for sep in ["|", "/", "·", "•", "-"])

    # Looks like a name pattern (Title Case words)
    name_pattern = re.findall(r'\b[A-Z][a-z]+(?:\s[A-Z][a-z.]+)+\b', line)
    has_names = len(name_pattern) >= 1

    # Short line (bylines are rarely long paragraphs)
    is_short = len(line.strip()) < 150

    return has_keyword and is_short and (has_separator or has_names)


def is_metadata_line(line: str) -> bool:
    """
    Detect metadata lines like timestamps, tags, categories.
    E.g. 'Published: 12 March 2026', 'Tags: ESG, Indonesia'
    """
    meta_keywords = [
        "published", "updated", "posted", "tags:", "kategori",
        "category", "topic", "label", "share:", "views:",
        "reading time", "menit membaca", "tanggal", "diperbarui",
        "diterbitkan", "dipublikasikan"
    ]
    line_lower = line.lower().strip()
    return any(line_lower.startswith(kw) or f" {kw}" in line_lower for kw in meta_keywords)


def clean_content(text: str, noise_phrases: list) -> str:
    if not text:
        return ""

    lines = text.split("\n")
    cleaned_lines = []

    for line in lines:
        line_stripped = line.strip()

        # Skip empty lines
        if not line_stripped:
            continue

        # Skip noise phrases
        if any(phrase.lower() in line_stripped.lower() for phrase in noise_phrases):
            continue

        # Skip reporter/editor bylines
        if is_byline(line_stripped):
            continue

        # Skip metadata lines
        if is_metadata_line(line_stripped):
            continue

        # Skip very short lines (likely boilerplate nav/menu items)
        if len(line_stripped) < 10:
            continue

        # Skip lines that are mostly non-alphanumeric
        alphanum_ratio = sum(c.isalnum() or c.isspace() for c in line_stripped) / len(line_stripped)
        if alphanum_ratio < 0.5:
            continue

        cleaned_lines.append(line_stripped)

    # Remove duplicate consecutive lines
    deduped = []
    prev = None
    for line in cleaned_lines:
        if line != prev:
            deduped.append(line)
        prev = line

    return "\n".join(deduped).strip()

# -----------------------------
# Sidebar: Noise Phrase Manager
# -----------------------------
st.sidebar.header("🗑️ Noise Phrase Manager")

noise_phrases = load_noise_phrases()

st.sidebar.markdown("**Current Noise Phrases:**")
phrases_text = st.sidebar.text_area(
    "One phrase per line (edit to add/remove):",
    value="\n".join(noise_phrases),
    height=300,
    label_visibility="collapsed"
)

if st.sidebar.button("💾 Save Noise Phrases"):
    updated_phrases = [p.strip() for p in phrases_text.split("\n") if p.strip()]
    save_noise_phrases(updated_phrases)
    noise_phrases = updated_phrases
    st.sidebar.success(f"✅ Saved {len(updated_phrases)} phrases!")
    st.cache_data.clear()

if st.sidebar.button("🔄 Reset to Default"):
    save_noise_phrases(DEFAULT_NOISE_PHRASES)
    noise_phrases = DEFAULT_NOISE_PHRASES
    st.sidebar.success("✅ Reset to defaults!")
    st.cache_data.clear()

# Reload from text area for live preview
noise_phrases = [p.strip() for p in phrases_text.split("\n") if p.strip()]

# -----------------------------
# Summary
# -----------------------------
all_links = list(scraped_data.keys())
cleaned_links = set(cleaned_data.keys())
missing_links = [l for l in all_links if l not in cleaned_links]
has_content = [l for l in all_links if scraped_data[l].get("content", "").strip() and not scraped_data[l].get("content", "").startswith("[Error")]

st.subheader("📊 Summary")
col1, col2, col3, col4 = st.columns(4)
col1.metric("📰 Total Scraped", len(all_links))
col2.metric("📄 Has Raw Content", len(has_content))
col3.metric("✅ Already Cleaned", len(cleaned_links))
col4.metric("⏳ Pending Clean", len(missing_links))

# -----------------------------
# Live Preview
# -----------------------------
st.markdown("---")
st.subheader("🔍 Live Preview — Before vs After Cleaning")

articles_with_content = {
    link: data for link, data in scraped_data.items()
    if data.get("content", "").strip() and not data.get("content", "").startswith("[Error")
}

if articles_with_content:
    preview_titles = {data.get("title", link): link for link, data in articles_with_content.items()}
    selected_title = st.selectbox("Select article to preview:", list(preview_titles.keys()))
    selected_link = preview_titles[selected_title]
    selected_data = scraped_data[selected_link]

    raw_content = selected_data.get("content", "")
    cleaned_preview = clean_content(raw_content, noise_phrases)

    col_before, col_after = st.columns(2)

    with col_before:
        st.markdown("**📄 Raw Content (Before)**")
        st.caption(f"{len(raw_content)} characters | {len(raw_content.split(chr(10)))} lines")
        st.text_area("Raw", raw_content, height=400, label_visibility="collapsed", key="raw_preview")

    with col_after:
        st.markdown("**✨ Cleaned Content (After)**")
        st.caption(f"{len(cleaned_preview)} characters | {len(cleaned_preview.split(chr(10)))} lines")
        st.text_area("Cleaned", cleaned_preview, height=400, label_visibility="collapsed", key="clean_preview")

    reduction = len(raw_content) - len(cleaned_preview)
    reduction_pct = (reduction / len(raw_content) * 100) if len(raw_content) > 0 else 0
    st.info(f"🔻 Removed **{reduction:,} characters** ({reduction_pct:.1f}% reduction)")

# -----------------------------
# Batch Clean
# -----------------------------
st.markdown("---")
st.subheader("🚀 Batch Clean & Save to `data/extra_text.json`")

clean_mode = st.radio(
    "Choose what to clean:",
    ["Only Pending (Not Yet Cleaned)", "All Articles (Overwrite)"],
    horizontal=True
)

links_to_clean = missing_links if clean_mode == "Only Pending (Not Yet Cleaned)" else all_links
links_to_clean = [l for l in links_to_clean if scraped_data[l].get("content", "").strip()]

st.info(f"Will clean **{len(links_to_clean)}** articles using **{len(noise_phrases)}** noise phrases.")

if st.button("🧹 Start Cleaning"):
    progress_bar = st.progress(0)
    status_text = st.empty()
    results_log = []

    for i, link in enumerate(links_to_clean):
        data = scraped_data[link]
        raw_content = data.get("content", "")
        status_text.text(f"Cleaning ({i+1}/{len(links_to_clean)}): {data.get('title', link)[:80]}...")

        cleaned = clean_content(raw_content, noise_phrases)

        cleaned_data[link] = {
            "title": data.get("title", ""),
            "company_name": data.get("company_name", ""),
            "company_code": data.get("company_code", ""),
            "keyword": data.get("keyword", ""),
            "published": data.get("published", ""),
            "source": data.get("source", ""),
            "link": link,
            "resolved_url": data.get("resolved_url", link),
            "raw_content_length": len(raw_content),
            "cleaned_content": cleaned,
            "cleaned_content_length": len(cleaned),
            "reduction_pct": round((len(raw_content) - len(cleaned)) / len(raw_content) * 100, 2) if raw_content else 0,
            "scraped_at": data.get("scraped_at", ""),
            "cleaned_at": pd.Timestamp.now().isoformat(),
        }

        results_log.append({
            "title": data.get("title", "N/A")[:60],
            "raw_chars": len(raw_content),
            "cleaned_chars": len(cleaned),
            "reduction_%": f"{cleaned_data[link]['reduction_pct']}%",
        })

        progress_bar.progress((i + 1) / len(links_to_clean))

    # Save to file
    os.makedirs("data", exist_ok=True)
    with open(CLEANED_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned_data, f, ensure_ascii=False, indent=2)

    status_text.text("✅ Cleaning complete!")
    st.success(f"✅ Saved {len(links_to_clean)} cleaned articles to `{CLEANED_FILE}`")

    st.markdown("#### 📋 Cleaning Results")
    st.dataframe(pd.DataFrame(results_log), use_container_width=True)
    st.cache_data.clear()

# -----------------------------
# Export
# -----------------------------
st.markdown("---")
st.subheader("📥 Export")

if cleaned_data:
    export_rows = []
    for link, d in cleaned_data.items():
        export_rows.append({
            "title": d.get("title", ""),
            "company_name": d.get("company_name", ""),
            "keyword": d.get("keyword", ""),
            "source": d.get("source", ""),
            "published": d.get("published", ""),
            "resolved_url": d.get("resolved_url", ""),
            "raw_content_length": d.get("raw_content_length", 0),
            "cleaned_content_length": d.get("cleaned_content_length", 0),
            "reduction_pct": d.get("reduction_pct", 0),
            "cleaned_content": d.get("cleaned_content", ""),
        })

    export_df = pd.DataFrame(export_rows)
    st.download_button(
        label="⬇️ Download Cleaned Content as CSV",
        data=export_df.to_csv(index=False),
        file_name="cleaned_news_content.csv",
        mime="text/csv"
    )
else:
    st.info("No cleaned data yet. Run the batch cleaner above first.")
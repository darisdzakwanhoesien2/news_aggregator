import streamlit as st
import json
import os
import pandas as pd
import re
from datetime import datetime
from _page_descriptions import render_page_description

# =====================================================
# CONFIG
# =====================================================
ARTICLE_DIR = "data/articles"
LOG_DIR = "data/logs"
EDIT_LOG_PATH = os.path.join(LOG_DIR, "edit_log.json")

os.makedirs(LOG_DIR, exist_ok=True)

# =====================================================
# PAGE SETUP
# =====================================================
st.set_page_config(
    page_title="📊 Scraped Articles Viewer",
    layout="wide"
)

st.title("📊 Scraped Articles Viewer")
render_page_description(__file__)
st.caption(
    "Time-series article viewer with website preview, editable text, and edit audit logs"
)

# =====================================================
# HELPERS
# =====================================================
def append_edit_log(entry: dict):
    """Append a single edit event to edit_log.json"""
    if os.path.exists(EDIT_LOG_PATH):
        try:
            with open(EDIT_LOG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
    else:
        data = []

    data.append(entry)

    with open(EDIT_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_updated_articles(df: pd.DataFrame):
    """
    Persist edited articles back into their original daily JSON files.
    Uses (date, source_file) grouping to ensure correct overwrite.
    """
    for (date, source_file), group in df.groupby(["date", "source_file"]):
        path = os.path.join(ARTICLE_DIR, source_file)

        records = (
            group
            .drop(columns=["date", "source_file"])
            .to_dict("records")
        )

        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)


# =====================================================
# DISCOVER ARTICLE FILES
# =====================================================
if not os.path.exists(ARTICLE_DIR):
    st.error(f"Article directory not found: {ARTICLE_DIR}")
    st.stop()

article_files = sorted(
    f for f in os.listdir(ARTICLE_DIR)
    if f.startswith("articles_") and f.endswith(".json")
)

if not article_files:
    st.warning("No article JSON files found.")
    st.stop()

# =====================================================
# FILE SELECTION (TIME-SERIES)
# =====================================================
selected_files = st.multiselect(
    "📅 Select article dates (files)",
    article_files,
    default=[article_files[-1]]
)

if not selected_files:
    st.info("Please select at least one date.")
    st.stop()

# =====================================================
# LOAD & MERGE ARTICLES
# =====================================================
articles = []

for fname in selected_files:
    path = os.path.join(ARTICLE_DIR, fname)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        match = re.search(r"articles_(\d{4}-\d{2}-\d{2})", fname)
        date = match.group(1) if match else "unknown"

        for item in data:
            item["date"] = date
            item["source_file"] = fname
            articles.append(item)

    except Exception as e:
        st.warning(f"Failed to load {fname}: {e}")

if not articles:
    st.warning("No articles loaded from selected files.")
    st.stop()

df = pd.DataFrame(articles)

# =====================================================
# VALIDATION
# =====================================================
required_cols = {"url", "text", "text_length", "date", "source_file"}
missing = required_cols - set(df.columns)
if missing:
    st.error(f"Missing required fields: {missing}")
    st.stop()

# =====================================================
# ================= TABLE VIEW ========================
# =====================================================
st.subheader("📋 Articles Table (Overview)")

table_df = df[["date", "url", "text_length"]].copy()
table_df["text_length"] = table_df["text_length"].astype(int)

st.dataframe(
    table_df,
    use_container_width=True,
    height=420
)

# =====================================================
# ================= DETAIL VIEW =======================
# =====================================================
st.markdown("---")
st.subheader("🔍 Article Detail View")

selected_url = st.selectbox(
    "Select article",
    table_df["url"].tolist()
)

selected_row = df[df["url"] == selected_url].iloc[0]

col_left, col_right = st.columns([1, 1.4])

# -----------------------------------------------------
# LEFT: URL + WEBSITE VIEW
# -----------------------------------------------------
with col_left:
    st.markdown("### 🌐 Website View")
    st.markdown(f"**Date:** {selected_row['date']}")
    st.markdown(f"**URL:** {selected_row['url']}")

    st.components.v1.iframe(
        src=selected_row["url"],
        height=520,
        scrolling=True
    )

# -----------------------------------------------------
# RIGHT: EDITABLE TEXT + SAVE LOGIC
# -----------------------------------------------------
with col_right:
    st.markdown("### 📄 Extracted Text (Editable)")
    st.markdown(f"**Text length:** {selected_row['text_length']} characters")

    edited_text = st.text_area(
        "Article Text",
        value=selected_row["text"],
        height=520,
        key=f"text_{selected_row['url']}"
    )

    if edited_text != selected_row["text"]:
        st.warning("⚠️ Text has been modified")

        if st.button("💾 Save Edits"):
            now = datetime.now().isoformat()

            # 1️⃣ Log edit metadata
            append_edit_log({
                "url": selected_row["url"],
                "date": selected_row["date"],
                "edited_at": now,
                "original_text_length": len(selected_row["text"]),
                "new_text_length": len(edited_text),
                "change_type": "manual_edit"
            })

            # 2️⃣ Update in-memory dataframe
            df.loc[df["url"] == selected_row["url"], "text"] = edited_text
            df.loc[df["url"] == selected_row["url"], "text_length"] = len(edited_text)

            # 3️⃣ Persist changes to disk
            save_updated_articles(df)

            st.success("✅ Edits saved and logged successfully")


# import streamlit as st
# import json
# import os
# import pandas as pd
# import re

# # =====================================================
# # Config
# # =====================================================
# ARTICLE_DIR = "data/articles"

# st.set_page_config(
#     page_title="📊 View Scraped Articles",
#     layout="wide"
# )

# st.title("📊 Scraped Articles Viewer")
# st.caption("Time-series viewer for scraped news articles")

# # =====================================================
# # Discover Article Files
# # =====================================================
# if not os.path.exists(ARTICLE_DIR):
#     st.error(f"Article directory not found: {ARTICLE_DIR}")
#     st.stop()

# article_files = sorted(
#     [
#         f for f in os.listdir(ARTICLE_DIR)
#         if f.startswith("articles_") and f.endswith(".json")
#     ]
# )

# if not article_files:
#     st.warning("No article files found.")
#     st.stop()

# # =====================================================
# # File Selection
# # =====================================================
# selected_files = st.multiselect(
#     "📅 Select article files (dates)",
#     article_files,
#     default=[article_files[-1]]  # latest by default
# )

# if not selected_files:
#     st.info("Please select at least one file.")
#     st.stop()

# # =====================================================
# # Load & Merge Data
# # =====================================================
# all_articles = []

# for fname in selected_files:
#     path = os.path.join(ARTICLE_DIR, fname)

#     try:
#         with open(path, "r", encoding="utf-8") as f:
#             data = json.load(f)

#         # Extract date from filename
#         match = re.search(r"articles_(\d{4}-\d{2}-\d{2})", fname)
#         date = match.group(1) if match else "unknown"

#         for item in data:
#             item["source_file"] = fname
#             item["date"] = date
#             all_articles.append(item)

#     except Exception as e:
#         st.warning(f"Failed to load {fname}: {e}")

# if not all_articles:
#     st.warning("No articles loaded from selected files.")
#     st.stop()

# df = pd.DataFrame(all_articles)

# # =====================================================
# # Basic Validation
# # =====================================================
# required_cols = {"url", "text", "text_length", "date"}
# missing = required_cols - set(df.columns)
# if missing:
#     st.error(f"Missing required fields: {missing}")
#     st.stop()

# # =====================================================
# # Layout
# # =====================================================
# col_left, col_right = st.columns([1, 1.4])

# # =====================================================
# # LEFT: Table View
# # =====================================================
# with col_left:
#     st.subheader("📋 Article Table")

#     table_df = df[["date", "url", "text_length"]].copy()
#     table_df["text_length"] = table_df["text_length"].astype(int)

#     st.dataframe(
#         table_df,
#         use_container_width=True,
#         height=500
#     )

# # =====================================================
# # RIGHT: Dropdown + Text View
# # =====================================================
# with col_right:
#     st.subheader("📄 Article Detail")

#     selected_url = st.selectbox(
#         "Select article URL",
#         df["url"].tolist()
#     )

#     selected_row = df[df["url"] == selected_url].iloc[0]

#     st.markdown(f"**Date:** {selected_row['date']}")
#     st.markdown(f"**URL:** {selected_row['url']}")
#     st.markdown(f"**Text length:** {selected_row['text_length']} characters")

#     st.text_area(
#         "Extracted Article Text",
#         value=selected_row["text"],
#         height=520
#     )


# import streamlit as st
# import json
# import os
# import pandas as pd

# # =====================================================
# # Config
# # =====================================================
# ARTICLE_PATH = "data/articles/articles_2025-12-19.json"

# st.set_page_config(
#     page_title="📊 View Scraped Articles",
#     layout="wide"
# )

# st.title("📊 Scraped Articles Viewer")
# st.caption("Visualize extracted articles as table + detailed view")

# # =====================================================
# # Load Data
# # =====================================================
# if not os.path.exists(ARTICLE_PATH):
#     st.error(f"Article file not found: {ARTICLE_PATH}")
#     st.stop()

# with open(ARTICLE_PATH, "r", encoding="utf-8") as f:
#     articles = json.load(f)

# if not articles:
#     st.warning("No articles found in the file.")
#     st.stop()

# # =====================================================
# # Convert to DataFrame
# # =====================================================
# df = pd.DataFrame(articles)

# # Ensure expected columns
# required_cols = {"url", "text", "text_length"}
# missing = required_cols - set(df.columns)
# if missing:
#     st.error(f"Missing required fields: {missing}")
#     st.stop()

# # =====================================================
# # Layout
# # =====================================================
# col_left, col_right = st.columns([1, 1.4])

# # =====================================================
# # LEFT: Table View
# # =====================================================
# with col_left:
#     st.subheader("📋 Article Table")

#     table_df = df[["url", "text_length"]].copy()
#     table_df["text_length"] = table_df["text_length"].astype(int)

#     st.dataframe(
#         table_df,
#         use_container_width=True,
#         height=450
#     )

# # =====================================================
# # RIGHT: Dropdown + Text View
# # =====================================================
# with col_right:
#     st.subheader("📄 Article Detail")

#     selected_url = st.selectbox(
#         "Select article URL",
#         df["url"].tolist()
#     )

#     selected_row = df[df["url"] == selected_url].iloc[0]

#     st.markdown(f"**URL:** {selected_row['url']}")
#     st.markdown(f"**Text length:** {selected_row['text_length']} characters")

#     st.text_area(
#         "Extracted Article Text",
#         value=selected_row["text"],
#         height=500
#     )

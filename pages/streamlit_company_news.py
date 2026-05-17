# import streamlit as st
# import pandas as pd
# import json
# from pathlib import Path
# import matplotlib.pyplot as plt
# import time
# import hashlib
# import re

# # =========================
# # PAGE CONFIG
# # =========================
# st.set_page_config(page_title="🏢 Company News Intelligence", layout="wide")
# st.title("🏢 Company News Intelligence Dashboard")
# st.caption("Refresh • Deduplication • Grouped Articles • Multi-query detection")

# # =========================
# # PATHS
# # =========================
# BASE_DIR = Path(__file__).resolve().parents[1]
# DATA_PATH = BASE_DIR / "data" / "news_dataset.json"

# # =========================
# # FILE SIGNATURE
# # =========================
# def get_file_signature(path: Path):
#     if not path.exists():
#         return None
#     stat = path.stat()
#     return (stat.st_mtime, stat.st_size)

# # =========================
# # NORMALIZATION
# # =========================
# def normalize_text(text: str) -> str:
#     if not isinstance(text, str):
#         return ""
#     text = text.lower()
#     text = re.sub(r"https?://\S+", "", text)
#     text = re.sub(r"[^a-z0-9\s]", "", text)
#     text = re.sub(r"\s+", " ", text).strip()
#     return text


# def compute_news_hash(row):
#     """
#     Stable fingerprint:
#     title + source + published date (day-level)
#     """
#     title = normalize_text(row.get("title", ""))
#     source = normalize_text(row.get("source", ""))

#     published = row.get("published")
#     if pd.notna(published):
#         published_day = pd.to_datetime(published).strftime("%Y-%m-%d")
#     else:
#         published_day = "unknown"

#     base = f"{title}|{source}|{published_day}"
#     return hashlib.md5(base.encode("utf-8")).hexdigest()

# # =========================
# # SESSION STATE
# # =========================
# if "file_sig" not in st.session_state:
#     st.session_state.file_sig = None

# # =========================
# # DATA LOADER
# # =========================
# @st.cache_data(show_spinner=False)
# def load_data_cached(file_sig):
#     with open(DATA_PATH, "r", encoding="utf-8") as f:
#         raw = json.load(f)

#     df = pd.DataFrame(raw)
#     df["published"] = pd.to_datetime(df["published"], errors="coerce")
#     df["keyword"] = df["keyword"].fillna("").str.lower()

#     # Compute stable hash
#     df["news_hash"] = df.apply(compute_news_hash, axis=1)
#     return df


# def load_data():
#     sig = get_file_signature(DATA_PATH)
#     if sig is None:
#         return pd.DataFrame()

#     if sig != st.session_state.file_sig:
#         st.cache_data.clear()
#         st.session_state.file_sig = sig

#     return load_data_cached(sig)

# # =========================
# # REFRESH CONTROLS
# # =========================
# c1, c2, c3, c4 = st.columns([1, 1, 2, 2])

# with c1:
#     if st.button("🔄 Refresh Now"):
#         st.cache_data.clear()
#         st.experimental_rerun()

# with c2:
#     auto_refresh = st.toggle("⏱ Auto Refresh", value=False)

# with c3:
#     refresh_interval = st.slider(
#         "Refresh interval (seconds)",
#         5, 120, 30, step=5,
#         disabled=not auto_refresh
#     )

# with c4:
#     sig = get_file_signature(DATA_PATH)
#     if sig:
#         st.caption(f"📁 File updated: {pd.to_datetime(sig[0], unit='s')}")
#     else:
#         st.caption("📁 Waiting for data file...")

# # =========================
# # LOAD DATA
# # =========================
# df = load_data()

# if auto_refresh:
#     time.sleep(refresh_interval)
#     st.experimental_rerun()

# if df.empty:
#     st.info("⏳ Waiting for news_dataset.json...")
#     st.stop()

# st.success(f"✅ Loaded {len(df)} records")

# # =========================
# # DATA QUALITY METRICS
# # =========================
# total_records = len(df)
# unique_news = df["news_hash"].nunique()
# duplicate_rows = total_records - unique_news

# m1, m2, m3 = st.columns(3)
# m1.metric("Total Records", total_records)
# m2.metric("Unique News", unique_news)
# m3.metric("Duplicate Rows", duplicate_rows)

# st.divider()

# # =========================
# # 🧩 DUPLICATE GROUP VIEW
# # =========================
# st.subheader("♻️ Duplicate Groups")

# dup_groups = (
#     df.groupby("news_hash")
#     .filter(lambda x: len(x) > 1)
#     .groupby("news_hash")
# )

# if dup_groups.ngroups == 0:
#     st.success("No duplicate groups detected 🎉")
# else:
#     st.warning(f"{dup_groups.ngroups} duplicate groups detected")

#     for idx, (news_hash, group) in enumerate(dup_groups, start=1):
#         title = group["title"].iloc[0]
#         source = group["source"].iloc[0]
#         count = len(group)
#         queries = sorted(set(group["query"].dropna()))
#         keywords = sorted(set(group["keyword"].dropna()))
#         published_range = (group["published"].min(), group["published"].max())

#         with st.expander(
#             f"🧩 Duplicate Group {idx} — {count} occurrences — {source}"
#         ):
#             st.markdown(f"**Title:** {title}")
#             st.markdown(f"**Source:** {source}")
#             st.markdown(f"**Queries:** `{', '.join(queries)}`")
#             st.markdown(f"**Keywords:** `{', '.join(keywords)}`")
#             st.markdown(
#                 f"**Published range:** {published_range[0]} → {published_range[1]}"
#             )

#             st.dataframe(
#                 group[
#                     [
#                         "published",
#                         "title",
#                         "source",
#                         "query",
#                         "keyword",
#                         "company_code",
#                         "link",
#                     ]
#                 ].sort_values("published"),
#                 use_container_width=True,
#             )

# st.divider()

# # =========================
# # COMPANY DROPDOWN
# # =========================
# company_map = (
#     df[["company_code", "company_name"]]
#     .drop_duplicates()
#     .sort_values("company_code")
# )

# labels = [
#     f"{row.company_code} — {row.company_name}"
#     for row in company_map.itertuples()
# ]

# selected_label = st.selectbox("🏢 Select Company", labels)
# selected_code = selected_label.split(" — ")[0]

# company_df = df[df["company_code"] == selected_code]

# st.info(f"📌 {selected_code}: {len(company_df)} records")

# # =========================
# # VISUALIZATIONS
# # =========================
# colA, colB = st.columns(2)

# # ---------- Source Distribution
# with colA:
#     st.subheader("🗞 Source Distribution")
#     source_counts = company_df["source"].value_counts()

#     fig1, ax1 = plt.subplots()
#     source_counts.plot(kind="bar", ax=ax1)
#     ax1.set_xlabel("Source")
#     ax1.set_ylabel("Articles")
#     st.pyplot(fig1)

# # ---------- Date Distribution
# with colB:
#     st.subheader("📅 Articles Over Time")

#     time_series = (
#         company_df
#         .dropna(subset=["published"])
#         .set_index("published")
#         .resample("D")
#         .size()
#     )

#     fig2, ax2 = plt.subplots()
#     time_series.plot(ax=ax2)
#     ax2.set_xlabel("Date")
#     ax2.set_ylabel("Articles")
#     st.pyplot(fig2)

# # ---------- Keyword Distribution
# st.subheader("🔑 Keyword Distribution")

# keyword_counts = (
#     company_df["keyword"]
#     .str.split(",")
#     .explode()
#     .str.strip()
#     .replace("", pd.NA)
#     .dropna()
#     .value_counts()
#     .head(20)
# )

# fig3, ax3 = plt.subplots()
# keyword_counts.plot(kind="barh", ax=ax3)
# ax3.set_xlabel("Frequency")
# st.pyplot(fig3)

# # =========================
# # 📋 GROUPED ARTICLE TABLE
# # =========================
# st.subheader("📋 Articles (Grouped)")

# def unique_join(series):
#     values = sorted(set(v for v in series.dropna() if str(v).strip()))
#     return ", ".join(values)

# grouped_df = (
#     company_df
#     .groupby("news_hash")
#     .agg(
#         published=("published", "min"),
#         title=("title", "first"),
#         source=("source", "first"),
#         query=("query", unique_join),
#         keyword=("keyword", unique_join),
#         link=("link", "first"),
#         occurrences=("news_hash", "count"),
#     )
#     .reset_index(drop=True)
#     .sort_values("published", ascending=False)
# )

# st.dataframe(
#     grouped_df[
#         ["published", "title", "source", "query", "keyword", "occurrences", "link"]
#     ],
#     use_container_width=True,
# )

import streamlit as st
import pandas as pd
import json
from pathlib import Path
import matplotlib.pyplot as plt
import time
import hashlib
import re
from _page_descriptions import render_page_description

# =========================
# PAGE CONFIG
# =========================
st.set_page_config(page_title="🏢 Company News Intelligence", layout="wide")
st.title("🏢 Company News Intelligence Dashboard")
render_page_description(__file__)
st.caption("Refresh • Deduplication • Company Overview • Grouped Articles")

# =========================
# PATHS
# =========================
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_PATH = BASE_DIR / "data" / "news_dataset.json"

# =========================
# FILE SIGNATURE
# =========================
def get_file_signature(path: Path):
    if not path.exists():
        return None
    stat = path.stat()
    return (stat.st_mtime, stat.st_size)

# =========================
# NORMALIZATION HELPERS
# =========================
def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = text.lower()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compute_news_hash(row):
    """
    Stable fingerprint for duplicate detection.
    """
    title = normalize_text(row.get("title", ""))
    source = normalize_text(row.get("source", ""))

    published = row.get("published")
    if pd.notna(published):
        published_day = pd.to_datetime(published).strftime("%Y-%m-%d")
    else:
        published_day = "unknown"

    base = f"{title}|{source}|{published_day}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()

# =========================
# SESSION STATE
# =========================
if "file_sig" not in st.session_state:
    st.session_state.file_sig = None

# =========================
# DATA LOADER
# =========================
@st.cache_data(show_spinner=False)
def load_data_cached(file_sig):
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    df = pd.DataFrame(raw)
    df["published"] = pd.to_datetime(df["published"], errors="coerce")
    df["keyword"] = df["keyword"].fillna("").str.lower()
    df["news_hash"] = df.apply(compute_news_hash, axis=1)
    return df


def load_data():
    sig = get_file_signature(DATA_PATH)
    if sig is None:
        return pd.DataFrame()

    if sig != st.session_state.file_sig:
        st.cache_data.clear()
        st.session_state.file_sig = sig

    return load_data_cached(sig)

# =========================
# REFRESH CONTROLS
# =========================
c1, c2, c3, c4 = st.columns([1, 1, 2, 2])

with c1:
    if st.button("🔄 Refresh Now"):
        st.cache_data.clear()
        st.experimental_rerun()

with c2:
    auto_refresh = st.toggle("⏱ Auto Refresh", value=False)

with c3:
    refresh_interval = st.slider(
        "Refresh interval (seconds)",
        5, 120, 30, step=5,
        disabled=not auto_refresh
    )

with c4:
    sig = get_file_signature(DATA_PATH)
    if sig:
        st.caption(f"📁 File updated: {pd.to_datetime(sig[0], unit='s')}")
    else:
        st.caption("📁 Waiting for data file...")

# =========================
# LOAD DATA
# =========================
df = load_data()

if auto_refresh:
    time.sleep(refresh_interval)
    st.experimental_rerun()

if df.empty:
    st.info("⏳ Waiting for news_dataset.json...")
    st.stop()

st.success(f"✅ Loaded {len(df)} records")

# =========================
# SIDEBAR — COMPANY NAVIGATION
# =========================
st.sidebar.header("🏢 Company Navigator")

company_summary = (
    df.groupby(["company_code", "company_name"])
    .size()
    .reset_index(name="articles")
    .sort_values("articles", ascending=False)
)

company_labels = [
    f"{row.company_code} — {row.company_name} ({row.articles})"
    for row in company_summary.itertuples()
]

selected_sidebar_label = st.sidebar.selectbox(
    "Quick Select Company",
    options=company_labels,
)

selected_sidebar_code = selected_sidebar_label.split(" — ")[0]

# =========================
# 📊 COMPANY DISTRIBUTION OVERVIEW
# =========================
st.subheader("📊 Company Coverage Overview")

colA, colB = st.columns([2, 1])

with colA:
    top_companies = company_summary.head(15).set_index("company_code")["articles"]
    fig_overview, ax_overview = plt.subplots()
    top_companies.plot(kind="bar", ax=ax_overview)
    ax_overview.set_xlabel("Company Code")
    ax_overview.set_ylabel("Articles")
    ax_overview.set_title("Top Companies by News Volume")
    st.pyplot(fig_overview)

with colB:
    st.markdown("### 🏆 Top Companies")
    st.dataframe(
        company_summary.head(15),
        use_container_width=True
    )

st.divider()

# =========================
# COMPANY DROPDOWN (MAIN)
# =========================
labels = [
    f"{row.company_code} — {row.company_name}"
    for row in company_summary.itertuples()
]

default_index = next(
    (i for i, lbl in enumerate(labels) if lbl.startswith(selected_sidebar_code)),
    0,
)

selected_label = st.selectbox(
    "🏢 Select Company (Detailed View)",
    labels,
    index=default_index,
)

selected_code = selected_label.split(" — ")[0]
company_df = df[df["company_code"] == selected_code]

st.info(f"📌 {selected_code}: {len(company_df)} records")

# =========================
# VISUALIZATIONS
# =========================
col1, col2 = st.columns(2)

with col1:
    st.subheader("🗞 Source Distribution")
    source_counts = company_df["source"].value_counts()
    fig1, ax1 = plt.subplots()
    source_counts.plot(kind="bar", ax=ax1)
    st.pyplot(fig1)

with col2:
    st.subheader("📅 Articles Over Time")
    time_series = (
        company_df
        .dropna(subset=["published"])
        .set_index("published")
        .resample("D")
        .size()
    )
    fig2, ax2 = plt.subplots()
    time_series.plot(ax=ax2)
    st.pyplot(fig2)

st.subheader("🔑 Keyword Distribution")

keyword_counts = (
    company_df["keyword"]
    .str.split(",")
    .explode()
    .str.strip()
    .replace("", pd.NA)
    .dropna()
    .value_counts()
    .head(20)
)

fig3, ax3 = plt.subplots()
keyword_counts.plot(kind="barh", ax=ax3)
st.pyplot(fig3)

# =========================
# 📋 GROUPED ARTICLE TABLE
# =========================
st.subheader("📋 Articles (Grouped if Duplicate Exists)")

def unique_join(series):
    values = sorted(set(v for v in series.dropna() if str(v).strip()))
    return ", ".join(values)

grouped_df = (
    company_df
    .groupby("news_hash")
    .agg(
        published=("published", "min"),
        title=("title", "first"),
        source=("source", "first"),
        query=("query", unique_join),
        keyword=("keyword", unique_join),
        link=("link", "first"),
        occurrences=("news_hash", "count"),
    )
    .reset_index(drop=True)
    .sort_values("published", ascending=False)
)

st.dataframe(
    grouped_df[
        ["published", "title", "source", "query", "keyword", "occurrences", "link"]
    ],
    use_container_width=True
)


# import streamlit as st
# import pandas as pd
# import json
# from pathlib import Path
# import matplotlib.pyplot as plt
# import time
# import hashlib
# import re

# # =========================
# # PAGE CONFIG
# # =========================
# st.set_page_config(page_title="🏢 Company News Intelligence", layout="wide")
# st.title("🏢 Company News Intelligence Dashboard")
# st.caption("Refresh • Deduplication • Grouped Articles")

# # =========================
# # PATHS
# # =========================
# BASE_DIR = Path(__file__).resolve().parents[1]
# DATA_PATH = BASE_DIR / "data" / "news_dataset.json"

# # =========================
# # FILE SIGNATURE
# # =========================
# def get_file_signature(path: Path):
#     if not path.exists():
#         return None
#     stat = path.stat()
#     return (stat.st_mtime, stat.st_size)

# # =========================
# # NORMALIZATION HELPERS
# # =========================
# def normalize_text(text: str) -> str:
#     if not isinstance(text, str):
#         return ""
#     text = text.lower()
#     text = re.sub(r"https?://\S+", "", text)
#     text = re.sub(r"[^a-z0-9\s]", "", text)
#     text = re.sub(r"\s+", " ", text).strip()
#     return text


# def compute_news_hash(row):
#     """
#     Stable fingerprint for duplicate detection.
#     """
#     title = normalize_text(row.get("title", ""))
#     source = normalize_text(row.get("source", ""))

#     published = row.get("published")
#     if pd.notna(published):
#         published_day = pd.to_datetime(published).strftime("%Y-%m-%d")
#     else:
#         published_day = "unknown"

#     base = f"{title}|{source}|{published_day}"
#     return hashlib.md5(base.encode("utf-8")).hexdigest()

# # =========================
# # SESSION STATE
# # =========================
# if "file_sig" not in st.session_state:
#     st.session_state.file_sig = None

# # =========================
# # DATA LOADER
# # =========================
# @st.cache_data(show_spinner=False)
# def load_data_cached(file_sig):
#     with open(DATA_PATH, "r", encoding="utf-8") as f:
#         raw = json.load(f)

#     df = pd.DataFrame(raw)
#     df["published"] = pd.to_datetime(df["published"], errors="coerce")
#     df["keyword"] = df["keyword"].fillna("").str.lower()

#     # Compute stable hash
#     df["news_hash"] = df.apply(compute_news_hash, axis=1)
#     return df


# def load_data():
#     sig = get_file_signature(DATA_PATH)
#     if sig is None:
#         return pd.DataFrame()

#     if sig != st.session_state.file_sig:
#         st.cache_data.clear()
#         st.session_state.file_sig = sig

#     return load_data_cached(sig)

# # =========================
# # REFRESH CONTROLS
# # =========================
# c1, c2, c3, c4 = st.columns([1, 1, 2, 2])

# with c1:
#     if st.button("🔄 Refresh Now"):
#         st.cache_data.clear()
#         st.experimental_rerun()

# with c2:
#     auto_refresh = st.toggle("⏱ Auto Refresh", value=False)

# with c3:
#     refresh_interval = st.slider(
#         "Refresh interval (seconds)",
#         5, 120, 30, step=5,
#         disabled=not auto_refresh
#     )

# with c4:
#     sig = get_file_signature(DATA_PATH)
#     if sig:
#         st.caption(f"📁 File updated: {pd.to_datetime(sig[0], unit='s')}")
#     else:
#         st.caption("📁 Waiting for data file...")

# # =========================
# # LOAD DATA
# # =========================
# df = load_data()

# if auto_refresh:
#     time.sleep(refresh_interval)
#     st.experimental_rerun()

# if df.empty:
#     st.info("⏳ Waiting for news_dataset.json...")
#     st.stop()

# st.success(f"✅ Loaded {len(df)} records")

# # =========================
# # COMPANY DROPDOWN
# # =========================
# company_map = (
#     df[["company_code", "company_name"]]
#     .drop_duplicates()
#     .sort_values("company_code")
# )

# labels = [
#     f"{row.company_code} — {row.company_name}"
#     for row in company_map.itertuples()
# ]

# selected_label = st.selectbox("🏢 Select Company", labels)
# selected_code = selected_label.split(" — ")[0]

# company_df = df[df["company_code"] == selected_code]

# st.info(f"📌 {selected_code}: {len(company_df)} records")

# # =========================
# # VISUALIZATIONS
# # =========================
# colA, colB = st.columns(2)

# with colA:
#     st.subheader("🗞 Source Distribution")
#     source_counts = company_df["source"].value_counts()
#     fig1, ax1 = plt.subplots()
#     source_counts.plot(kind="bar", ax=ax1)
#     st.pyplot(fig1)

# with colB:
#     st.subheader("📅 Articles Over Time")
#     time_series = (
#         company_df
#         .dropna(subset=["published"])
#         .set_index("published")
#         .resample("D")
#         .size()
#     )
#     fig2, ax2 = plt.subplots()
#     time_series.plot(ax=ax2)
#     st.pyplot(fig2)

# st.subheader("🔑 Keyword Distribution")

# keyword_counts = (
#     company_df["keyword"]
#     .str.split(",")
#     .explode()
#     .str.strip()
#     .replace("", pd.NA)
#     .dropna()
#     .value_counts()
#     .head(20)
# )

# fig3, ax3 = plt.subplots()
# keyword_counts.plot(kind="barh", ax=ax3)
# st.pyplot(fig3)

# # =========================
# # 📋 GROUPED ARTICLE TABLE
# # =========================
# st.subheader("📋 Articles (Grouped if Duplicate Exists)")

# def unique_join(series):
#     values = sorted(set(v for v in series.dropna() if str(v).strip()))
#     return ", ".join(values)

# grouped_df = (
#     company_df
#     .groupby("news_hash")
#     .agg(
#         published=("published", "min"),
#         title=("title", "first"),
#         source=("source", "first"),
#         query=("query", unique_join),
#         keyword=("keyword", unique_join),
#         link=("link", "first"),
#         occurrences=("news_hash", "count"),
#     )
#     .reset_index(drop=True)
#     .sort_values("published", ascending=False)
# )

# st.dataframe(
#     grouped_df[
#         ["published", "title", "source", "query", "keyword", "occurrences", "link"]
#     ],
#     use_container_width=True
# )



# import streamlit as st
# import pandas as pd
# import json
# from pathlib import Path
# import matplotlib.pyplot as plt
# import time
# import hashlib
# import re

# # =========================
# # PAGE CONFIG
# # =========================
# st.set_page_config(page_title="🏢 Company News Intelligence", layout="wide")
# st.title("🏢 Company News Intelligence Dashboard")
# st.caption("Refresh • Deduplication • Multi-query collision detection")

# # =========================
# # PATHS
# # =========================
# BASE_DIR = Path(__file__).resolve().parents[1]
# DATA_PATH = BASE_DIR / "data" / "news_dataset.json"

# # =========================
# # FILE SIGNATURE
# # =========================
# def get_file_signature(path: Path):
#     if not path.exists():
#         return None
#     stat = path.stat()
#     return (stat.st_mtime, stat.st_size)

# # =========================
# # NORMALIZATION HELPERS
# # =========================
# def normalize_text(text: str) -> str:
#     """
#     Normalize text for deduplication.
#     """
#     if not isinstance(text, str):
#         return ""
#     text = text.lower()
#     text = re.sub(r"https?://\S+", "", text)   # remove urls
#     text = re.sub(r"[^a-z0-9\s]", "", text)    # remove punctuation
#     text = re.sub(r"\s+", " ", text).strip()
#     return text


# def compute_news_hash(row):
#     """
#     Stable fingerprint for duplicate detection.
#     Uses title + source + published date (day).
#     """
#     title = normalize_text(row.get("title", ""))
#     source = normalize_text(row.get("source", ""))
    
#     published = row.get("published")
#     if pd.notna(published):
#         published_day = pd.to_datetime(published).strftime("%Y-%m-%d")
#     else:
#         published_day = "unknown"

#     base = f"{title}|{source}|{published_day}"
#     return hashlib.md5(base.encode("utf-8")).hexdigest()

# # =========================
# # SESSION STATE
# # =========================
# if "file_sig" not in st.session_state:
#     st.session_state.file_sig = None

# # =========================
# # DATA LOADER
# # =========================
# @st.cache_data(show_spinner=False)
# def load_data_cached(file_sig):
#     with open(DATA_PATH, "r", encoding="utf-8") as f:
#         raw = json.load(f)

#     df = pd.DataFrame(raw)

#     df["published"] = pd.to_datetime(df["published"], errors="coerce")
#     df["keyword"] = df["keyword"].fillna("").str.lower()

#     # Compute stable hash
#     df["news_hash"] = df.apply(compute_news_hash, axis=1)

#     return df


# def load_data():
#     sig = get_file_signature(DATA_PATH)

#     if sig is None:
#         return pd.DataFrame()

#     if sig != st.session_state.file_sig:
#         st.cache_data.clear()
#         st.session_state.file_sig = sig

#     return load_data_cached(sig)

# # =========================
# # REFRESH CONTROLS
# # =========================
# c1, c2, c3, c4 = st.columns([1, 1, 2, 2])

# with c1:
#     if st.button("🔄 Refresh Now"):
#         st.cache_data.clear()
#         st.experimental_rerun()

# with c2:
#     auto_refresh = st.toggle("⏱ Auto Refresh", value=False)

# with c3:
#     refresh_interval = st.slider(
#         "Refresh interval (seconds)",
#         5, 120, 30, step=5,
#         disabled=not auto_refresh
#     )

# with c4:
#     sig = get_file_signature(DATA_PATH)
#     if sig:
#         st.caption(f"📁 File updated: {pd.to_datetime(sig[0], unit='s')}")
#     else:
#         st.caption("📁 Waiting for data file...")

# # =========================
# # LOAD DATA
# # =========================
# df = load_data()

# if auto_refresh:
#     time.sleep(refresh_interval)
#     st.experimental_rerun()

# if df.empty:
#     st.info("⏳ Waiting for news_dataset.json...")
#     st.stop()

# st.success(f"✅ Loaded {len(df)} records")

# # =========================
# # DUPLICATE ANALYSIS
# # =========================
# total_records = len(df)
# unique_news = df["news_hash"].nunique()
# duplicate_rows = total_records - unique_news

# duplicate_df = (
#     df[df.duplicated("news_hash", keep=False)]
#     .sort_values(["news_hash", "published"])
# )

# # Multi-query collisions
# multi_query_df = (
#     df.groupby("news_hash")
#     .agg(
#         title=("title", "first"),
#         source=("source", "first"),
#         queries=("query", lambda x: sorted(set(x))),
#         count=("query", "count"),
#     )
#     .reset_index()
# )

# multi_query_df = multi_query_df[multi_query_df["queries"].apply(len) > 1]

# # =========================
# # DATA QUALITY PANEL
# # =========================
# st.subheader("🧹 Data Quality")

# q1, q2, q3 = st.columns(3)
# q1.metric("Total Records", total_records)
# q2.metric("Unique News", unique_news)
# q3.metric("Duplicate Rows", duplicate_rows)

# with st.expander("♻️ Duplicate News Records"):
#     if duplicate_df.empty:
#         st.success("No duplicates detected 🎉")
#     else:
#         st.warning(f"{len(duplicate_df)} duplicate rows detected")
#         st.dataframe(
#             duplicate_df[
#                 ["published", "title", "source", "query", "company_code", "news_hash"]
#             ],
#             use_container_width=True
#         )

# with st.expander("🔁 Multi-Query Collisions"):
#     if multi_query_df.empty:
#         st.success("No multi-query collisions 🎉")
#     else:
#         st.warning(f"{len(multi_query_df)} news appear under multiple queries")
#         st.dataframe(
#             multi_query_df[
#                 ["title", "source", "count", "queries"]
#             ],
#             use_container_width=True
#         )

# st.divider()

# # =========================
# # COMPANY DROPDOWN
# # =========================
# company_map = (
#     df[["company_code", "company_name"]]
#     .drop_duplicates()
#     .sort_values("company_code")
# )

# labels = [
#     f"{row.company_code} — {row.company_name}"
#     for row in company_map.itertuples()
# ]

# selected_label = st.selectbox("🏢 Select Company", labels)
# selected_code = selected_label.split(" — ")[0]

# company_df = df[df["company_code"] == selected_code]

# st.info(f"📌 {selected_code}: {len(company_df)} records")

# # =========================
# # VISUALIZATIONS
# # =========================
# colA, colB = st.columns(2)

# # ---------- Source Distribution
# with colA:
#     st.subheader("🗞 Source Distribution")
#     source_counts = company_df["source"].value_counts()

#     fig1, ax1 = plt.subplots()
#     source_counts.plot(kind="bar", ax=ax1)
#     ax1.set_xlabel("Source")
#     ax1.set_ylabel("Articles")
#     st.pyplot(fig1)

# # ---------- Date Distribution
# with colB:
#     st.subheader("📅 Articles Over Time")

#     time_series = (
#         company_df
#         .dropna(subset=["published"])
#         .set_index("published")
#         .resample("D")
#         .size()
#     )

#     fig2, ax2 = plt.subplots()
#     time_series.plot(ax=ax2)
#     ax2.set_xlabel("Date")
#     ax2.set_ylabel("Articles")
#     st.pyplot(fig2)

# # ---------- Keyword Distribution
# st.subheader("🔑 Keyword Distribution")

# keyword_counts = (
#     company_df["keyword"]
#     .str.split(",")
#     .explode()
#     .str.strip()
#     .replace("", pd.NA)
#     .dropna()
#     .value_counts()
#     .head(20)
# )

# fig3, ax3 = plt.subplots()
# keyword_counts.plot(kind="barh", ax=ax3)
# ax3.set_xlabel("Frequency")
# st.pyplot(fig3)

# # ---------- Article Table
# st.subheader("📋 Articles")

# display_df = company_df[
#     ["published", "title", "source", "query", "keyword", "link"]
# ].sort_values("published", ascending=False)

# st.dataframe(display_df, use_container_width=True)


# import streamlit as st
# import pandas as pd
# import json
# from pathlib import Path
# import matplotlib.pyplot as plt
# import time
# import hashlib

# # =========================
# # PAGE CONFIG
# # =========================
# st.set_page_config(page_title="🏢 Company News Intelligence", layout="wide")
# st.title("🏢 Company News Intelligence Dashboard")
# st.caption("Refresh • Deduplication • Multi-query collision detection")

# # =========================
# # PATHS
# # =========================
# BASE_DIR = Path(__file__).resolve().parents[1]
# DATA_PATH = BASE_DIR / "data" / "news_dataset.json"

# # =========================
# # FILE SIGNATURE
# # =========================
# def get_file_signature(path: Path):
#     if not path.exists():
#         return None
#     stat = path.stat()
#     return (stat.st_mtime, stat.st_size)


# # =========================
# # HASHING FOR DUPLICATES
# # =========================
# def compute_news_hash(row):
#     """
#     Create a stable fingerprint for detecting duplicate news.
#     """
#     base = f"{row.get('title','')}|{row.get('decoded_url','')}|{row.get('published','')}"
#     return hashlib.md5(base.encode("utf-8")).hexdigest()


# # =========================
# # SESSION STATE
# # =========================
# if "file_sig" not in st.session_state:
#     st.session_state.file_sig = None

# if "last_refresh" not in st.session_state:
#     st.session_state.last_refresh = None


# # =========================
# # DATA LOADER
# # =========================
# @st.cache_data(show_spinner=False)
# def load_data_cached(file_sig):
#     with open(DATA_PATH, "r", encoding="utf-8") as f:
#         raw = json.load(f)

#     df = pd.DataFrame(raw)

#     df["published"] = pd.to_datetime(df["published"], errors="coerce")
#     df["keyword"] = df["keyword"].fillna("").str.lower()

#     # Hash for deduplication
#     df["news_hash"] = df.apply(compute_news_hash, axis=1)

#     return df


# def load_data():
#     sig = get_file_signature(DATA_PATH)

#     if sig is None:
#         return pd.DataFrame()

#     if sig != st.session_state.file_sig:
#         st.cache_data.clear()
#         st.session_state.file_sig = sig
#         st.session_state.last_refresh = pd.Timestamp.utcnow()

#     return load_data_cached(sig)


# # =========================
# # REFRESH CONTROLS
# # =========================
# c1, c2, c3, c4 = st.columns([1, 1, 2, 2])

# with c1:
#     if st.button("🔄 Refresh Now"):
#         st.cache_data.clear()
#         st.experimental_rerun()

# with c2:
#     auto_refresh = st.toggle("⏱ Auto Refresh", value=False)

# with c3:
#     refresh_interval = st.slider(
#         "Refresh interval (seconds)",
#         5, 120, 30, step=5,
#         disabled=not auto_refresh
#     )

# with c4:
#     sig = get_file_signature(DATA_PATH)
#     if sig:
#         st.caption(f"📁 File updated: {pd.to_datetime(sig[0], unit='s')}")
#     else:
#         st.caption("📁 Waiting for data file...")

# # =========================
# # LOAD DATA
# # =========================
# df = load_data()

# if auto_refresh:
#     time.sleep(refresh_interval)
#     st.experimental_rerun()

# if df.empty:
#     st.info("⏳ Waiting for news_dataset.json...")
#     st.stop()

# st.success(f"✅ Loaded {len(df)} records")

# # =========================
# # DUPLICATE ANALYSIS
# # =========================
# total_records = len(df)
# unique_news = df["news_hash"].nunique()
# duplicate_rows = total_records - unique_news

# duplicate_df = (
#     df[df.duplicated("news_hash", keep=False)]
#     .sort_values("news_hash")
# )

# # Multi-query collisions (same news hash across multiple queries)
# multi_query_df = (
#     df.groupby("news_hash")
#     .agg(
#         queries=("query", lambda x: list(set(x))),
#         count=("query", "count"),
#         title=("title", "first"),
#         source=("source", "first"),
#     )
#     .reset_index()
# )

# multi_query_df = multi_query_df[multi_query_df["queries"].apply(len) > 1]

# # =========================
# # DATA QUALITY PANEL
# # =========================
# st.subheader("🧹 Data Quality")

# q1, q2, q3 = st.columns(3)
# q1.metric("Total Records", total_records)
# q2.metric("Unique News", unique_news)
# q3.metric("Duplicate Rows", duplicate_rows)

# with st.expander("♻️ Duplicate News Records"):
#     if duplicate_df.empty:
#         st.success("No duplicates detected 🎉")
#     else:
#         st.warning(f"{len(duplicate_df)} duplicate rows detected")
#         st.dataframe(
#             duplicate_df[
#                 ["title", "source", "published", "query", "company_code", "news_hash"]
#             ],
#             use_container_width=True
#         )

# with st.expander("🔁 Multi-Query Collisions"):
#     if multi_query_df.empty:
#         st.success("No multi-query collisions 🎉")
#     else:
#         st.warning(f"{len(multi_query_df)} news appear under multiple queries")
#         st.dataframe(
#             multi_query_df[
#                 ["title", "source", "count", "queries"]
#             ],
#             use_container_width=True
#         )

# st.divider()

# # =========================
# # COMPANY DROPDOWN
# # =========================
# company_map = (
#     df[["company_code", "company_name"]]
#     .drop_duplicates()
#     .sort_values("company_code")
# )

# labels = [
#     f"{row.company_code} — {row.company_name}"
#     for row in company_map.itertuples()
# ]

# selected_label = st.selectbox("🏢 Select Company", labels)
# selected_code = selected_label.split(" — ")[0]

# company_df = df[df["company_code"] == selected_code]

# st.info(f"📌 {selected_code}: {len(company_df)} records")

# # =========================
# # VISUALIZATIONS
# # =========================
# colA, colB = st.columns(2)

# # ---------- Source Distribution
# with colA:
#     st.subheader("🗞 Source Distribution")
#     source_counts = company_df["source"].value_counts()

#     fig1, ax1 = plt.subplots()
#     source_counts.plot(kind="bar", ax=ax1)
#     ax1.set_xlabel("Source")
#     ax1.set_ylabel("Articles")
#     st.pyplot(fig1)

# # ---------- Date Distribution
# with colB:
#     st.subheader("📅 Articles Over Time")

#     time_series = (
#         company_df
#         .dropna(subset=["published"])
#         .set_index("published")
#         .resample("W")
#         .size()
#     )

#     fig2, ax2 = plt.subplots()
#     time_series.plot(ax=ax2)
#     ax2.set_xlabel("Week")
#     ax2.set_ylabel("Articles")
#     st.pyplot(fig2)

# # ---------- Keyword Distribution
# st.subheader("🔑 Keyword Distribution")

# keyword_counts = (
#     company_df["keyword"]
#     .str.split(",")
#     .explode()
#     .str.strip()
#     .replace("", pd.NA)
#     .dropna()
#     .value_counts()
#     .head(20)
# )

# fig3, ax3 = plt.subplots()
# keyword_counts.plot(kind="barh", ax=ax3)
# ax3.set_xlabel("Frequency")
# st.pyplot(fig3)

# # ---------- Article Table
# st.subheader("📋 Articles")

# display_df = company_df[
#     ["published", "title", "source", "query", "keyword", "link"]
# ].sort_values("published", ascending=False)

# st.dataframe(display_df, use_container_width=True)

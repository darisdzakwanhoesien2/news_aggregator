import streamlit as st
import pandas as pd
import json
from pathlib import Path

# =========================
# PAGE CONFIG
# =========================
st.set_page_config(page_title="🏢 Company Coverage Mapper", layout="wide")
st.title("🏢 Company Coverage Mapper")
st.caption("Compare ESG master list vs News dataset coverage")

# =========================
# PATHS
# =========================
BASE_DIR = Path(__file__).resolve().parents[1]

NEWS_PATH = BASE_DIR / "data" / "news_dataset.json"
ESG_PATH  = BASE_DIR / "data" / "esg_companies.json"

# =========================
# LOAD DATA
# =========================

@st.cache_data
def load_json(path: Path):
    if not path.exists():
        st.error(f"❌ Missing file: {path}")
        st.stop()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


news_raw = load_json(NEWS_PATH)
esg_raw  = load_json(ESG_PATH)

news_df = pd.DataFrame(news_raw)
esg_df  = pd.DataFrame(esg_raw)

# Normalize codes
news_df["company_code"] = news_df["company_code"].astype(str).str.upper().str.strip()
esg_df["code"] = esg_df["code"].astype(str).str.upper().str.strip()

# =========================
# EXTRACT COMPANY SETS
# =========================

news_codes = set(news_df["company_code"].dropna().unique())
esg_codes  = set(esg_df["code"].dropna().unique())

matched = sorted(news_codes & esg_codes)
missing_in_news = sorted(esg_codes - news_codes)
extra_in_news   = sorted(news_codes - esg_codes)

# =========================
# EXPORT MISSING CODES (AUTO BRIDGE)
# =========================

AUTO_MISSING_PATH = BASE_DIR / "data" / "missing_companies.json"

with open(AUTO_MISSING_PATH, "w") as f:
    json.dump({
        "missing_codes": missing_in_news,
        "timestamp": pd.Timestamp.utcnow().isoformat()
    }, f, indent=2)

# =========================
# METRICS
# =========================

c1, c2, c3, c4 = st.columns(4)
c1.metric("ESG Companies", len(esg_codes))
c2.metric("Companies in News", len(news_codes))
c3.metric("Matched", len(matched))
c4.metric("Missing in News", len(missing_in_news))

st.divider()

# =========================
# TABLES
# =========================

st.subheader("❌ ESG Companies Missing in News")
missing_df = (
    esg_df[esg_df["code"].isin(missing_in_news)]
    .sort_values("code")
)
st.dataframe(missing_df, use_container_width=True)

st.subheader("⚠️ Companies Appearing in News but Not in ESG List")
extra_df = pd.DataFrame(extra_in_news, columns=["company_code"])
st.dataframe(extra_df, use_container_width=True)

with st.expander("🔍 Debug"):
    st.json({
        "missing_codes": missing_in_news,
        "extra_codes": extra_in_news
    })

st.success("✅ missing_companies.json updated automatically")

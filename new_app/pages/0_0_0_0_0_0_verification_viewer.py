import json
from pathlib import Path
from datetime import datetime

import streamlit as st
import pandas as pd
import altair as alt

st.set_page_config(page_title="Verification Viewer", layout="wide")
st.title("🔎 Verification — Viewer")

# search project for verification.json files
ROOT = Path(__file__).resolve().parents[2]  # news_collection/
ver_paths = sorted(ROOT.rglob("verification.json"))

if not ver_paths:
    st.warning(f"No verification.json files found under {ROOT}")
    st.stop()

sel = st.selectbox("Select verification file", options=[str(p.relative_to(ROOT)) for p in ver_paths])
sel_path = ROOT / sel

try:
    raw = json.loads(sel_path.read_text(encoding="utf-8"))
except Exception as e:
    st.error(f"Failed to load JSON: {e}")
    st.stop()

# header metrics
col1, col2, col3 = st.columns(3)
col1.metric("Company", raw.get("company", "—"))
col2.metric("Model", raw.get("model", "—"))
col3.metric("Timestamp", raw.get("timestamp", datetime.utcnow().isoformat()))

# load tables
scores = pd.DataFrame(raw.get("scores", []))
verifs = pd.DataFrame(raw.get("verifications", []))
answers = pd.DataFrame(raw.get("answers", []))

st.markdown("### ✅ Summary")
c1, c2, c3 = st.columns(3)
c1.metric("Total Final Score", raw.get("total_final_score", "—"))
c2.metric("Total Max Score", raw.get("total_max_score", "—"))
c3.metric("Pct Verified", f"{raw.get('pct_verified', '—')}%")

st.markdown("### 🔍 Verification status distribution")
if verifs.empty:
    st.info("No verification entries to display.")
else:
    counts = verifs["verification_status"].fillna("NOT_FOUND").value_counts().reset_index()
    counts.columns = ["status", "count"]
    chart = alt.Chart(counts).mark_bar().encode(
        x=alt.X("status:N", title="Status"),
        y=alt.Y("count:Q", title="Count"),
        color=alt.Color("status:N", legend=None)
    ).properties(height=240)
    st.altair_chart(chart, use_container_width=True)

st.markdown("### 📊 Pillar / Score table")
if not scores.empty:
    # normalise column names
    scores = scores.rename(columns=lambda c: c.strip())
    st.dataframe(scores)
    st.download_button("⬇️ Download scores CSV", scores.to_csv(index=False).encode("utf-8"),
                       file_name=f"scores_{sel_path.stem}.csv", mime="text/csv")
else:
    st.info("No scores recorded in this verification file.")

st.markdown("### 📋 Per-question evidence & reasoning")
if not verifs.empty:
    qid = st.selectbox("Select question ID", options=verifs["id"].tolist())
    row = verifs[verifs["id"] == qid].iloc[0].to_dict()
    st.markdown(f"- **ID:** {row.get('id')}")
    st.markdown(f"- **Status:** {row.get('verification_status')}")
    st.markdown(f"- **Confidence:** {row.get('confidence')}")
    st.markdown(f"- **Evidence page:** {row.get('evidence_page') or '—'}")
    st.markdown("**Evidence quote**")
    st.code(row.get("evidence_quote") or "No quote provided")
    st.markdown("**Reasoning**")
    st.write(row.get("reasoning") or "No reasoning provided")
else:
    st.info("No verifications present in file.")

st.markdown("### 🗂 Raw LLM reply (truncated)")
raw_reply = raw.get("raw_llm_reply", "")
if raw_reply:
    st.text_area("Raw LLM reply", value=raw_reply[:2000], height=240)
else:
    st.info("No raw LLM reply stored.")
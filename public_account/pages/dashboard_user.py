import json
from pathlib import Path
from datetime import datetime

import streamlit as st
import pandas as pd
import altair as alt

# Page config
st.set_page_config(page_title="Verification Viewer", layout="wide")
st.title("🔎 Verification — Visualiser")

# locate verification files under public_account/user_data
ROOT = Path(__file__).parent.parent
USER_DATA_DIR = ROOT / "user_data"

def find_verifications(root: Path):
    return sorted(root.rglob("verification.json"))

ver_files = find_verifications(USER_DATA_DIR)

if not ver_files:
    st.warning(f"No verification.json files found under {USER_DATA_DIR}")
    st.stop()

# choose file
options = [p.relative_to(USER_DATA_DIR) for p in ver_files]
sel = st.selectbox("Select verification file", options=options, index=0)
sel_path = USER_DATA_DIR / str(sel)

# load
try:
    raw = json.loads(sel_path.read_text(encoding="utf-8"))
except Exception as e:
    st.error(f"Failed to load JSON: {e}")
    st.stop()

# show metadata
meta_col1, meta_col2, meta_col3 = st.columns(3)
meta_col1.metric("Company", raw.get("company", "—"))
meta_col2.metric("Model", raw.get("model", "—"))
meta_col3.metric("Timestamp", raw.get("timestamp", datetime.utcnow().isoformat()))

# prepare dataframes
scores = pd.DataFrame(raw.get("scores", []))
verifs = pd.DataFrame(raw.get("verifications", []))

# normalize columns if present with spaces
if not scores.empty:
    scores = scores.rename(columns=lambda c: c.strip())

# top-level metrics
total_final = raw.get("total_final_score", None)
pct_verified = raw.get("pct_verified", None)
col_a, col_b = st.columns(2)
if total_final is not None:
    col_a.metric("Total Final Score", f"{total_final}")
if pct_verified is not None:
    col_b.metric("Pct Verified", f"{pct_verified}%")

st.markdown("### ✅ Verification status distribution")
if verifs.empty:
    st.info("No verification entries to display.")
else:
    status_counts = verifs["verification_status"].fillna("NOT_FOUND").value_counts().reset_index()
    status_counts.columns = ["status", "count"]
    chart = alt.Chart(status_counts).mark_bar().encode(
        x=alt.X("status:N", title="Verification Status"),
        y=alt.Y("count:Q", title="Count"),
        color=alt.Color("status:N", legend=None)
    ).properties(height=240)
    st.altair_chart(chart, use_container_width=True)

st.markdown("### 📊 Pillar-level scores")
if not scores.empty and {"Pillar", "Final Score", "Max Score"}.issubset(set(scores.columns)):
    pillar = scores.groupby("Pillar").agg({"Final Score": "sum", "Max Score": "sum"}).reset_index()
    pillar["pct"] = (pillar["Final Score"] / pillar["Max Score"] * 100).round(1)
    bar = alt.Chart(pillar).transform_fold(
        ["Final Score", "Max Score"],
        as_=["type", "score"]
    ).mark_bar().encode(
        x=alt.X("Pillar:N", sort="-y"),
        y=alt.Y("score:Q", title="Points"),
        color="type:N",
        column=alt.Column("type:N", header=alt.Header(labelAngle=0))
    ).properties(height=220)
    st.altair_chart(bar, use_container_width=True)
    st.dataframe(pillar.sort_values("pct", ascending=False).reset_index(drop=True))
else:
    st.info("Scores table missing expected columns (Pillar / Final Score / Max Score).")

st.markdown("### 📋 Question-level scores")
if not scores.empty:
    score_tbl = scores.copy()
    # show useful columns if available
    show_cols = [c for c in ["ID", "Pillar", "Question", "Selected", "Final Score", "Max Score", "Status", "Confidence", "Evidence Quote"] if c in score_tbl.columns]
    st.dataframe(score_tbl[show_cols].sort_values(["Pillar","ID"]).reset_index(drop=True))
    csv = score_tbl.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download scores CSV", csv, file_name=f"scores_{sel_path.stem}.csv", mime="text/csv")
else:
    st.info("No scores to show.")

st.markdown("### 🔍 Per-question evidence & reasoning")
if not verifs.empty:
    sel_q = st.selectbox("Select question ID", options=verifs["id"].tolist())
    row = verifs[verifs["id"] == sel_q].iloc[0].to_dict()
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

st.markdown("### 🗂 Raw LLM reply (first 2000 chars)")
raw_reply = raw.get("raw_llm_reply", "")
if raw_reply:
    st.text_area("Raw LLM reply", value=raw_reply[:2000], height=240)
else:
    st.info("No raw LLM reply stored.")
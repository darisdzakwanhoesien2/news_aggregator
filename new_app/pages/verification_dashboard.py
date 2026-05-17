import json
from pathlib import Path
from statistics import mean

import streamlit as st
import pandas as pd
import altair as alt
from _page_descriptions import render_page_description

st.set_page_config(page_title="Verification Dashboard", layout="wide")
st.title("📈 Verification — Dashboard")
render_page_description(__file__)

ROOT = Path(__file__).resolve().parents[2]
ver_files = sorted(ROOT.rglob("verification.json"))

if not ver_files:
    st.warning(f"No verification.json files found under {ROOT}")
    st.stop()

# load summaries
rows = []
ver_entries = []
for p in ver_files:
    try:
        j = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        continue
    rows.append({
        "path": str(p.relative_to(ROOT)),
        "company": j.get("company", "—"),
        "timestamp": j.get("timestamp"),
        "model": j.get("model"),
        "total_final_score": j.get("total_final_score", 0),
        "total_max_score": j.get("total_max_score", 0),
        "pct_verified": j.get("pct_verified", 0),
        "status": j.get("status", "unknown"),
        "n_verifications": len(j.get("verifications", [])),
    })
    for v in j.get("verifications", []):
        v2 = v.copy()
        v2["_source"] = str(p.relative_to(ROOT))
        ver_entries.append(v2)

df_summary = pd.DataFrame(rows)
df_ver = pd.DataFrame(ver_entries)

st.markdown("### Overview")
c1, c2, c3 = st.columns(3)
c1.metric("Verification files", len(df_summary))
c2.metric("Total verifications", len(df_ver))
c3.metric("Avg pct verified", f"{df_summary['pct_verified'].dropna().mean():.2f}%")

st.markdown("### Files by company")
if not df_summary.empty:
    st.dataframe(df_summary.sort_values(["company","timestamp"], ascending=[True, False]).reset_index(drop=True))
    csv = df_summary.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download summary CSV", csv, file_name="verification_summary.csv", mime="text/csv")
else:
    st.info("No summary rows.")

st.markdown("### Status distribution across all verifications")
if df_ver.empty:
    st.info("No verification entries available to aggregate.")
else:
    counts = df_ver["verification_status"].fillna("NOT_FOUND").value_counts().reset_index()
    counts.columns = ["status", "count"]
    bar = alt.Chart(counts).mark_bar().encode(
        x=alt.X("status:N", title="Status"),
        y=alt.Y("count:Q", title="Count"),
        color=alt.Color("status:N", legend=None)
    ).properties(height=240)
    st.altair_chart(bar, use_container_width=True)

st.markdown("### Pillar heatmap (if pillar present)")
if not df_ver.empty and "pillar" in df_ver.columns:
    pivot = df_ver.groupby(["pillar","verification_status"]).size().reset_index(name="count")
    chart = alt.Chart(pivot).mark_bar().encode(
        x="pillar:N",
        y="count:Q",
        color="verification_status:N",
        column="verification_status:N"
    ).properties(height=220)
    st.altair_chart(chart, use_container_width=True)
else:
    st.info("No pillar data found in verifications.")

st.markdown("### Inspect verifications table")
if not df_ver.empty:
    # show useful columns if exist
    show_cols = [c for c in ["_source","id","verification_status","confidence","evidence_page"] if c in df_ver.columns or c=="_source"]
    st.dataframe(df_ver[show_cols].sort_values(["_source","id"]).reset_index(drop=True))
else:
    st.info("No per-question verifications to show.")

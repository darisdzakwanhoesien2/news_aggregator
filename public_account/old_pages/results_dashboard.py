import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

# Page config
st.set_page_config(page_title="Results Dashboard", page_icon="📈", layout="wide")
st.title("📈 Verification Results Dashboard")

BASE_DIR = Path(__file__).resolve().parents[1]
USER_DATA = BASE_DIR / "user_data"

st.markdown("Aggregate metrics across all sessions and companies.")

def find_all_verifications(root: Path) -> list[dict]:
    results = []
    if not root.exists():
        return results
    for user_dir in sorted(root.iterdir()):
        if not user_dir.is_dir():
            continue
        sessions = user_dir / "sessions"
        if not sessions.exists():
            continue
        for s in sorted(sessions.iterdir()):
            out_f = s / "outputs" / "verification.json"
            if out_f.exists():
                try:
                    j = json.loads(out_f.read_text(encoding="utf-8"))
                    j["_user"] = user_dir.name
                    j["_session_path"] = str(s)
                    results.append(j)
                except Exception:
                    continue
    return results

with st.spinner("Loading results..."):
    rows = find_all_verifications(USER_DATA)
    df = pd.DataFrame(rows)

if df.empty:
    st.info("No verification results found. Run verification to populate dashboard.")
    st.stop()

# normalize for metrics
df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
df["pct_verified"] = pd.to_numeric(df["pct_verified"], errors="coerce").fillna(0)
df["total_final_score"] = pd.to_numeric(df["total_final_score"], errors="coerce").fillna(0)
df["total_max_score"] = pd.to_numeric(df["total_max_score"], errors="coerce").fillna(0)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Sessions", len(df))
col2.metric("Avg % Verified", f"{df['pct_verified'].mean():.1f}%")
col3.metric("Avg Final Score", f"{df['total_final_score'].mean():.1f}")
col4.metric("Avg Max Score", f"{df['total_max_score'].mean():.1f}")

st.divider()
st.subheader("Distribution of % Verified")
st.bar_chart(df["pct_verified"])

st.divider()
st.subheader("Top companies by latest pct_verified")
# pick latest per company (company field in payload)
latest = df.sort_values("timestamp").groupby("company", as_index=False).last()
top = latest.sort_values("pct_verified", ascending=False).head(10)
st.dataframe(top[["company", "session_id", "pct_verified", "timestamp"]])

st.divider()
st.subheader("Raw sessions table")
st.dataframe(df[["company","session_id","_user","timestamp","pct_verified","model"]].sort_values("timestamp", ascending=False), use_container_width=True)

st.divider()
st.download_button(
    "⬇️ Download combined results CSV",
    data=df.to_csv(index=False),
    file_name=f"verification_aggregated_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.csv",
    mime="text/csv",
)
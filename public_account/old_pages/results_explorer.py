import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Results Explorer", page_icon="🔎", layout="wide")
st.title("🔎 Results Explorer — Per-session details")

BASE_DIR = Path(__file__).resolve().parents[1]
USER_DATA = BASE_DIR / "user_data"

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

with st.spinner("Loading sessions..."):
    items = find_all_verifications(USER_DATA)
    if not items:
        st.info("No verification outputs found.")
        st.stop()
    df = pd.DataFrame(items)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.sort_values("timestamp", ascending=False)

company_filter = st.selectbox("Filter by company", options=["All"] + sorted(df["company"].dropna().unique().tolist()))
if company_filter != "All":
    df = df[df["company"] == company_filter]

session_choice = st.selectbox("Pick a session", options=df["session_id"].tolist(), format_func=lambda x: x)
if session_choice:
    rec = next((r for r in items if r.get("session_id") == session_choice), None)
    if rec:
        st.header(f"Session: {rec.get('session_id')} — {rec.get('company')}")
        st.markdown(f"- User: `{rec.get('_user')}`")
        st.markdown(f"- Model: `{rec.get('model')}`")
        st.markdown(f"- Timestamp: `{rec.get('timestamp')}`")
        st.markdown(f"- % Verified: **{rec.get('pct_verified')}%**")
        st.divider()
        st.subheader("Scores")
        scores = pd.DataFrame(rec.get("scores", [])).fillna("")
        if not scores.empty:
            st.dataframe(scores, use_container_width=True)
            st.download_button(
                "⬇️ Download session scores CSV",
                data=scores.to_csv(index=False),
                file_name=f"{rec.get('company')}_{rec.get('session_id')}_scores.csv",
                mime="text/csv",
            )
        else:
            st.info("No score table found in this session output.")

        st.subheader("Verifications JSON")
        st.code(json.dumps(rec.get("verifications", []), ensure_ascii=False, indent=2), language="json")

        st.subheader("Raw LLM Reply")
        raw = rec.get("raw_llm_reply", "") or ""
        st.text_area("Raw reply", value=raw, height=300)

        # link to files on disk
        sess_path = Path(rec.get("_session_path", ""))
        if sess_path.exists():
            st.subheader("Session files")
            st.write(f"Session folder: `{sess_path}`")
            outputs = sess_path / "outputs"
            if outputs.exists():
                files = sorted([p for p in outputs.iterdir()])
                for f in files:
                    st.markdown(f"- {f.name} — {f.stat().st_size} bytes")
            else:
                st.info("No outputs folder present on disk.")
    else:
        st.error("Selected session not found.")
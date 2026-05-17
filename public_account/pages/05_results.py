import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_compat import get_query_params, set_query_params
from _page_descriptions import render_page_description

# optional HTML renderer
try:
    from pages.components.results_renderer import render_results_html
except Exception:
    render_results_html = None

st.set_page_config(page_title="Verification Results", page_icon="📋", layout="wide")
render_page_description(__file__)

# ── helpers ────────────────────────────────────────────────────────────────────
def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Return the first candidate column name that exists in df."""
    for c in candidates:
        if c in df.columns:
            return c
    return None

def render_results_from_json(result_json: dict):
    """Lightweight fallback renderer (Streamlit native) if HTML renderer missing."""
    if not result_json:
        st.info("No results to display.")
        return
    df = pd.DataFrame(result_json.get("scores", []))
    st.header("📋 Verification Results")
    st.write(f"Company: **{result_json.get('company','—')}**  ·  Session: `{result_json.get('session_id','')}`")
    if render_results_html:
        # Prefer the polished HTML view if available
        render_results_html(result_json, height=820)
        return
    if df.empty:
        st.info("No score rows available.")
        return
    final_col = _find_col(df, ["Final Score", "Final_Score", "FinalScore"])
    max_col   = _find_col(df, ["Max Score", "Max_Score", "MaxScore"])
    total_final = df[final_col].sum() if final_col else 0
    total_max   = df[max_col].sum() if max_col else 0
    pct = round(total_final / total_max * 100, 1) if total_max else 0.0
    c1, c2, c3 = st.columns(3)
    c1.metric("Final Score", f"{total_final:.1f}")
    c2.metric("Max Score", f"{total_max:.1f}")
    c3.metric("% Verified", f"{pct}%")
    st.subheader("Score table")
    st.dataframe(df, use_container_width=True)
    st.subheader("Raw verifications")
    st.code(json.dumps(result_json.get("verifications", []), ensure_ascii=False, indent=2), language="json")


# ── Standalone page entry point ────────────────────────────────────────────────
def main():
    # back button
    if st.button("← Back to Dashboard"):
        try:
            st.switch_page("pages/03_dashboard.py")
        except Exception:
            set_query_params()
            st.experimental_rerun()

    # Primary source: dashboard stored payload
    payload = st.session_state.get("_result_json")
    # Secondary: if no payload, attempt to load outputs from query params (user/session)
    if not payload:
        try:
            params = get_query_params()
            user = params.get("user", [None])[0]
            sess = params.get("session", [None])[0]
            if user and sess:
                path = Path(__file__).resolve().parents[1] / "user_data" / user / "sessions" / sess / "outputs" / "verification.json"
                if path.exists():
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    # populate session_state for consistency
                    st.session_state["_result_json"] = payload
                    st.session_state["_result_user"] = user
                    st.session_state["_result_sess"] = sess
        except Exception:
            pass

    if not payload:
        st.warning("No result loaded. From dashboard click 'View' on a session to open results here.")
        st.stop()

    # Render using helper
    render_results_from_json(payload)

if __name__ == "__main__":
    main()

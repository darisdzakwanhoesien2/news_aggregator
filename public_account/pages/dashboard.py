import streamlit as st
from pathlib import Path
import json

DATA_FILE = Path(__file__).parent.parent / "users.json"

def load_users_map():
    if not DATA_FILE.exists():
        return {}
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8") or "{}")
        return {u["username"]: u for u in raw.get("users", [])}
    except Exception:
        return {}

st.set_page_config(page_title="Personal Page", layout="centered")
st.title("👤 Personal Page / Dashboard")

st.markdown(
    """
    <style>
    .card {
      background: #ffffff;
      padding: 18px;
      border-radius: 10px;
      border: 1px solid #e6eef8;
      box-shadow: 0 1px 6px rgba(0,0,0,0.04);
    }
    .muted { color: #6b7280; font-size:12px; }
    </style>
    """,
    unsafe_allow_html=True,
)

user_key = st.session_state.get("user")

# if no session, check URL query params (rehydrate session if present)
if not user_key:
    params = st.experimental_get_query_params()
    if "user" in params and params["user"]:
        st.session_state["user"] = params["user"][0]
        user_key = st.session_state.get("user")

if not user_key:
    st.warning("You are not logged in. Please login first.")
    st.markdown("- [Go to Login](/login)")
else:
    users = load_users_map()
    user = users.get(user_key, {})
    with st.container():
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader(f"Hello, {user_key}")
        created = user.get("created_at", "Unknown")
        st.write("Account created:", created)
        st.write("Username:", user_key)
        st.markdown('<div class="muted">This is your personal dashboard. You can extend this page to show saved articles, preferences, or other personal data.</div>', unsafe_allow_html=True)
        if st.button("Logout"):
            if "user" in st.session_state:
                del st.session_state["user"]
            st.experimental_set_query_params()  # clear url param
            st.success("Logged out.")
            st.experimental_rerun()
        st.markdown('</div>', unsafe_allow_html=True)
import streamlit as st
from pathlib import Path
import hashlib
import json
from datetime import datetime
import streamlit.components.v1 as components

DATA_FILE = Path(__file__).parent.parent / "users.json"

def load_users():
    if not DATA_FILE.exists():
        return {}
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8") or "{}")
        users = raw.get("users", [])
        # map and ensure role exists
        out = {}
        for u in users:
            if "role" not in u:
                u["role"] = "UKM"
            out[u["username"]] = u
        return out
    except Exception:
        return {}

def verify_password(stored_salt_hex, stored_hash_hex, password_plain):
    salt = bytes.fromhex(stored_salt_hex)
    h = hashlib.pbkdf2_hmac("sha256", password_plain.encode("utf-8"), salt, 100_000)
    return h.hex() == stored_hash_hex

st.set_page_config(page_title="Login", layout="centered")
st.title("🔐 Login")

# already logged in view
current_user = st.session_state.get("user")
current_role = st.session_state.get("role")
if current_user:
    role_label = f" ({current_role})" if current_role else ""
    st.success(f"Already logged in as {current_user}{role_label}")
    st.markdown(f"- [Go to your personal page / dashboard](/dashboard?user={current_user})")
    if st.button("Logout"):
        if "user" in st.session_state:
            del st.session_state["user"]
        if "role" in st.session_state:
            del st.session_state["role"]
        st.experimental_set_query_params()  # clear url param
        st.experimental_rerun()
    st.stop()

st.markdown(
    """
    <style>
    .card {
      background: #f8fafc;
      padding: 18px;
      border-radius: 10px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.container():
    st.markdown('<div class="card">', unsafe_allow_html=True)
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    submitted = st.button("Login")
    st.markdown('</div>', unsafe_allow_html=True)

if submitted:
    users = load_users()
    user = users.get(username)
    if not user:
        st.error("User not found. Please register first.")
    else:
        ok = verify_password(user["salt"], user["password_hash"], password)
        if ok:
            # persist login and set URL param so dashboard can rehydrate
            st.session_state["user"] = username
            st.session_state["role"] = user.get("role", "UKM")
            st.experimental_set_query_params(user=username)
            # navigate to the dashboard immediately
            components.html(f"<script>window.location.href='/dashboard?user={username}';</script>", height=0)
            st.stop()
        else:
            st.error("Invalid password.")
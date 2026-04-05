import streamlit as st
from pathlib import Path
import hashlib
import os
import json
from datetime import datetime

DATA_FILE = Path(__file__).parent.parent / "users.json"

def load_users():
    if not DATA_FILE.exists():
        return []
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8") or "{}")
        users = raw.get("users", [])
        # ensure legacy users have a role
        for u in users:
            if "role" not in u:
                u["role"] = "UKM"
        return users
    except Exception:
        return []

def save_users(users_list):
    DATA_FILE.write_text(json.dumps({"users": users_list}, indent=2), encoding="utf-8")

def username_exists(username, users_list):
    return any(u["username"] == username for u in users_list)

def hash_password(password_plain):
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", password_plain.encode("utf-8"), salt, 100_000)
    return salt.hex(), h.hex()

st.set_page_config(page_title="Register", layout="centered")
st.title("📝 Register")

st.markdown(
    """
    <style>
    .card {
      background: linear-gradient(180deg,#ffffff,#f7fbff);
      padding: 18px;
      border-radius: 10px;
      border: 1px solid #e6eef8;
    }
    .muted { color: #6b7280; font-size:12px; }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.container():
    st.markdown('<div class="card">', unsafe_allow_html=True)
    username = st.text_input("Choose a username")
    role = st.selectbox("Role", options=["UKM", "Supplier", "Bank"], index=0, help="UKM can fill forms; Supplier/Bank can view multiple UKM profiles/scores")
    password = st.text_input("Choose a password", type="password")
    password2 = st.text_input("Repeat password", type="password")
    submitted = st.button("Create account")
    st.markdown('</div>', unsafe_allow_html=True)

if submitted:
    if not username or not password:
        st.error("Username and password are required.")
    elif password != password2:
        st.error("Passwords do not match.")
    else:
        users = load_users()
        if username_exists(username, users):
            st.error("Username already taken.")
        else:
            salt_hex, hash_hex = hash_password(password)
            user = {
                "username": username,
                "role": role,
                "salt": salt_hex,
                "password_hash": hash_hex,
                "created_at": datetime.utcnow().isoformat() + "Z"
            }
            users.append(user)
            save_users(users)
            st.success("Account created successfully. You can now go to Login.")
            st.markdown("- [Go to Login](/login)")
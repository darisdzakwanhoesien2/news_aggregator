import streamlit as st
from pathlib import Path
import hashlib
import os
import json
from datetime import datetime
from _page_descriptions import render_page_description

# ====================== CONFIGURATION ======================
ROOT = Path(__file__).parent.parent
USER_DATA_DIR = ROOT / "user_data"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = USER_DATA_DIR / "users.json"

# ====================== HELPER FUNCTIONS ======================
def load_users():
    if not DATA_FILE.exists():
        return []
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8") or "{}")
        users = raw.get("users", [])
        for u in users:
            if "role" not in u:
                u["role"] = "UKM"
        return users
    except Exception:
        return []

def save_users(users_list):
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps({"users": users_list}, indent=2, ensure_ascii=False), encoding="utf-8")

def username_exists(username, users_list):
    return any(u["username"] == username for u in users_list)

def hash_password(password_plain):
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", password_plain.encode("utf-8"), salt, 100_000)
    return salt.hex(), h.hex()

# ====================== PAGE CONFIG ======================
st.set_page_config(
    page_title="Register • UKM System",
    layout="centered",
    initial_sidebar_state="collapsed"
)
render_page_description(__file__)

# ====================== CUSTOM CSS + HTML ======================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    .main {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        min-height: 100vh;
    }

    .register-container {
        max-width: 460px;
        margin: 40px auto;
        background: white;
        border-radius: 20px;
        box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
        overflow: hidden;
    }

    .header {
        background: linear-gradient(135deg, #4f46e5, #7c3aed);
        color: white;
        padding: 35px 20px;
        text-align: center;
    }

    .header h1 {
        margin: 0;
        font-size: 28px;
        font-weight: 700;
    }

    .header p {
        margin: 10px 0 0 0;
        opacity: 0.9;
        font-size: 15px;
    }

    .card-content {
        padding: 40px 35px;
    }

    .stTextInput > div > div > input,
    .stSelectbox > div > div {
        border-radius: 12px;
        border: 2px solid #e2e8f0;
        padding: 14px 16px;
        font-size: 16px;
        transition: all 0.3s ease;
    }

    .stTextInput > div > div > input:focus,
    .stSelectbox > div > div:focus-within {
        border-color: #6366f1;
        box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15);
    }

    .stButton > button {
        background: linear-gradient(135deg, #4f46e5, #7c3aed);
        color: white;
        border: none;
        padding: 14px 20px;
        font-size: 16px;
        font-weight: 600;
        border-radius: 12px;
        height: 52px;
        transition: all 0.3s ease;
    }

    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 20px rgba(79, 70, 229, 0.3);
    }

    .success-msg {
        background: #ecfdf5;
        color: #10b981;
        padding: 14px 18px;
        border-radius: 12px;
        border-left: 5px solid #10b981;
        margin: 15px 0;
    }

    .footer {
        text-align: center;
        margin-top: 30px;
        color: #64748b;
        font-size: 14px;
    }
</style>
""", unsafe_allow_html=True)

# ====================== MAIN UI ======================
st.markdown("""
<div class="register-container">
    <div class="header">
        <h1>📝 Create Account</h1>
        <p>Join the UKM Management System</p>
    </div>
""", unsafe_allow_html=True)

st.markdown('<div class="card-content">', unsafe_allow_html=True)

# Form Fields
username = st.text_input("Choose a username", placeholder="Enter username")
role = st.selectbox(
    "Select your role",
    options=["UKM", "Supplier", "Bank"],
    index=0,
    help="UKM can fill forms • Supplier & Bank can view multiple profiles"
)

password = st.text_input("Choose a password", type="password", placeholder="Create a strong password")
password2 = st.text_input("Repeat password", type="password", placeholder="Confirm your password")

# Password requirements hint
st.markdown("""
<div style="font-size:13px; color:#64748b; margin:8px 0 20px 0;">
    Password must be at least 8 characters with uppercase, lowercase, and a number.
</div>
""", unsafe_allow_html=True)

# Submit Button
if st.button("Create Account", use_container_width=True, type="primary"):
    if not username or not password:
        st.error("❌ Username and password are required.")
    elif password != password2:
        st.error("❌ Passwords do not match.")
    elif len(password) < 8:
        st.error("❌ Password must be at least 8 characters long.")
    else:
        users = load_users()
        if username_exists(username, users):
            st.error("❌ Username already taken. Please choose another one.")
        else:
            # Create new user
            salt_hex, hash_hex = hash_password(password)
            new_user = {
                "username": username,
                "role": role,
                "salt": salt_hex,
                "password_hash": hash_hex,
                "created_at": datetime.utcnow().isoformat() + "Z"
            }
            
            users.append(new_user)
            save_users(users)

            st.success("✅ Account created successfully!")
            st.markdown("""
            <div style="text-align:center; margin:20px 0;">
                <a href="/login" style="background:#4f46e5; color:white; padding:12px 28px; 
                border-radius:12px; text-decoration:none; font-weight:600;">
                    Go to Login
                </a>
            </div>
            """, unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)  # End card-content
st.markdown('</div>', unsafe_allow_html=True)  # End register-container

# Footer
st.markdown("""
<div class="footer">
    © 2026 UKM Management System • Secure Registration
</div>
""", unsafe_allow_html=True)

# import streamlit as st
# from pathlib import Path
# import hashlib
# import os
# import json
# from datetime import datetime

# # new: central user_data folder
# ROOT = Path(__file__).parent.parent
# USER_DATA_DIR = ROOT / "user_data"
# USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
# DATA_FILE = USER_DATA_DIR / "users.json"

# def load_users():
#     if not DATA_FILE.exists():
#         return []
#     try:
#         raw = json.loads(DATA_FILE.read_text(encoding="utf-8") or "{}")
#         users = raw.get("users", [])
#         # ensure legacy users have a role
#         for u in users:
#             if "role" not in u:
#                 u["role"] = "UKM"
#         return users
#     except Exception:
#         return []

# def save_users(users_list):
#     USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
#     DATA_FILE.write_text(json.dumps({"users": users_list}, indent=2), encoding="utf-8")

# def username_exists(username, users_list):
#     return any(u["username"] == username for u in users_list)

# def hash_password(password_plain):
#     salt = os.urandom(16)
#     h = hashlib.pbkdf2_hmac("sha256", password_plain.encode("utf-8"), salt, 100_000)
#     return salt.hex(), h.hex()

# st.set_page_config(page_title="Register", layout="centered")
# st.title("📝 Register")

# st.markdown(
#     """
#     <style>
#     .card {
#       background: linear-gradient(180deg,#ffffff,#f7fbff);
#       padding: 18px;
#       border-radius: 10px;
#       border: 1px solid #e6eef8;
#     }
#     .muted { color: #6b7280; font-size:12px; }
#     </style>
#     """,
#     unsafe_allow_html=True,
# )

# with st.container():
#     st.markdown('<div class="card">', unsafe_allow_html=True)
#     username = st.text_input("Choose a username")
#     role = st.selectbox("Role", options=["UKM", "Supplier", "Bank"], index=0, help="UKM can fill forms; Supplier/Bank can view multiple UKM profiles/scores")
#     password = st.text_input("Choose a password", type="password")
#     password2 = st.text_input("Repeat password", type="password")
#     submitted = st.button("Create account")
#     st.markdown('</div>', unsafe_allow_html=True)

# if submitted:
#     if not username or not password:
#         st.error("Username and password are required.")
#     elif password != password2:
#         st.error("Passwords do not match.")
#     else:
#         users = load_users()
#         if username_exists(username, users):
#             st.error("Username already taken.")
#         else:
#             salt_hex, hash_hex = hash_password(password)
#             user = {
#                 "username": username,
#                 "role": role,
#                 "salt": salt_hex,
#                 "password_hash": hash_hex,
#                 "created_at": datetime.utcnow().isoformat() + "Z"
#             }
#             users.append(user)
#             save_users(users)
#             st.success("Account created successfully. You can now go to Login.")
#             st.markdown("- [Go to Login](/login)")

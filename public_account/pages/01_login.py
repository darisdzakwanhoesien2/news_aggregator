import streamlit as st
from pathlib import Path
import hashlib
import json
import secrets
from datetime import datetime
import streamlit.components.v1 as components
from streamlit_compat import set_query_params

# ====================== CONFIGURATION ======================
ROOT = Path(__file__).parent.parent
USER_DATA_DIR = ROOT / "user_data"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = USER_DATA_DIR / "users.json"
ROOT_USERS_FILE = ROOT / "users.json"

# ====================== HELPER FUNCTIONS ======================
def load_users():
    for f in (DATA_FILE, ROOT_USERS_FILE):
        if not f.exists():
            continue
        try:
            raw = json.loads(f.read_text(encoding="utf-8") or "{}")
            users = raw.get("users", [])
            out = {}
            for u in users:
                if "role" not in u:
                    u["role"] = "UKM"
                out[u["username"]] = u
            if out:
                return out, f
        except Exception:
            continue
    return {}, DATA_FILE

def save_users(users_dict: dict, filepath: Path):
    data = {"users": list(users_dict.values())}
    filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def verify_password(stored_salt_hex, stored_hash_hex, password_plain):
    salt = bytes.fromhex(stored_salt_hex)
    h = hashlib.pbkdf2_hmac("sha256", password_plain.encode("utf-8"), salt, 100_000)
    return h.hex() == stored_hash_hex

def hash_password(password_plain: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", password_plain.encode("utf-8"), salt, 100_000)
    return salt.hex(), h.hex()

def validate_password(pw: str) -> list[str]:
    errors = []
    if len(pw) < 8:
        errors.append("At least 8 characters.")
    if not any(c.isupper() for c in pw):
        errors.append("At least one uppercase letter.")
    if not any(c.islower() for c in pw):
        errors.append("At least one lowercase letter.")
    if not any(c.isdigit() for c in pw):
        errors.append("At least one digit.")
    return errors

# ====================== STREAMLIT CONFIG ======================
st.set_page_config(
    page_title="Login • UKM System",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ====================== CUSTOM HTML + CSS ======================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    .main {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        min-height: 100vh;
    }

    .login-container {
        max-width: 420px;
        margin: 40px auto;
        background: white;
        border-radius: 20px;
        box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
        overflow: hidden;
    }

    .header {
        background: linear-gradient(135deg, #4f46e5, #7c3aed);
        color: white;
        padding: 30px 20px;
        text-align: center;
    }

    .header h1 {
        margin: 0;
        font-size: 28px;
        font-weight: 700;
    }

    .header p {
        margin: 8px 0 0 0;
        opacity: 0.9;
        font-size: 15px;
    }

    .card-content {
        padding: 40px 35px;
    }

    .stTextInput > div > div > input {
        border-radius: 12px;
        border: 2px solid #e2e8f0;
        padding: 14px 16px;
        font-size: 16px;
        transition: all 0.3s ease;
    }

    .stTextInput > div > div > input:focus {
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

    .tab-container {
        margin-top: 10px;
    }

    .success-msg {
        background: #ecfdf5;
        color: #10b981;
        padding: 12px 16px;
        border-radius: 10px;
        border-left: 5px solid #10b981;
    }

    .error-msg {
        background: #fef2f2;
        color: #ef4444;
        padding: 12px 16px;
        border-radius: 10px;
        border-left: 5px solid #ef4444;
    }

    .footer {
        text-align: center;
        margin-top: 30px;
        color: #64748b;
        font-size: 14px;
    }
</style>
""", unsafe_allow_html=True)

# ====================== SESSION CHECK ======================
current_user = st.session_state.get("user")
current_role = st.session_state.get("role")

if current_user:
    st.markdown(f"""
    <div style="text-align:center; padding:40px;">
        <h2>✅ Already Logged In</h2>
        <p>You are logged in as <strong>{current_user}</strong> 
        {f'({current_role})' if current_role else ''}</p>
        <a href="/dashboard?user={current_user}" target="_self" 
           style="background:#4f46e5;color:white;padding:12px 24px;border-radius:12px;text-decoration:none;">
            Go to Dashboard
        </a>
    </div>
    """, unsafe_allow_html=True)

    if st.button("Logout", use_container_width=True):
        for k in ("user", "role"):
            st.session_state.pop(k, None)
        set_query_params()
        st.experimental_rerun()
    st.stop()

# ====================== MAIN UI ======================
st.markdown("""
<div class="login-container">
    <div class="header">
        <h1>🔐 Welcome Back</h1>
        <p>Sign in to access your UKM dashboard</p>
    </div>
""", unsafe_allow_html=True)

tab_login, tab_reset = st.tabs(["🔑 Login", "🔄 Reset Password"])

# ──────────────────────── LOGIN TAB ────────────────────────
with tab_login:
    st.markdown('<div class="card-content">', unsafe_allow_html=True)

    username = st.text_input("Username", placeholder="Enter your username", key="login_username")
    password = st.text_input("Password", type="password", placeholder="Enter your password", key="login_password")

    if st.button("Login", use_container_width=True, type="primary"):
        if not username or not password:
            st.error("Please fill in both username and password.")
        else:
            users, _ = load_users()
            user = users.get(username)

            if not user:
                st.error("❌ User not found.")
            else:
                if verify_password(user["salt"], user["password_hash"], password):
                    st.session_state["user"] = username
                    st.session_state["role"] = user.get("role", "UKM")
                    st.success("✅ Login successful! Redirecting...")

                    components.html(
                        f"""
                        <script>
                            window.location.href = '/dashboard?user={username}';
                        </script>
                        """,
                        height=0
                    )
                    st.stop()
                else:
                    st.error("❌ Invalid password.")

    st.markdown('</div>', unsafe_allow_html=True)

# ──────────────────────── RESET PASSWORD TAB ────────────────────────
with tab_reset:
    st.markdown('<div class="card-content">', unsafe_allow_html=True)

    st.caption("Enter your current credentials to set a new password.")

    with st.form("reset_form", clear_on_submit=True):
        r_username = st.text_input("Username", placeholder="Your username")
        r_current_pw = st.text_input("Current Password", type="password", placeholder="Current password")
        r_new_pw = st.text_input("New Password", type="password", placeholder="New password")
        r_confirm_pw = st.text_input("Confirm New Password", type="password", placeholder="Confirm new password")

        st.caption("New password must be at least 8 characters with uppercase, lowercase, and a number.")

        reset_btn = st.form_submit_button("Reset Password", use_container_width=True, type="primary")

    if reset_btn:
        if not r_username:
            st.error("Please enter your username.")
        elif r_username not in (users := load_users()[0]):
            st.error(f"❌ Username `{r_username}` not found.")
        elif not r_current_pw:
            st.error("Please enter your current password.")
        elif not verify_password(users[r_username]["salt"], users[r_username]["password_hash"], r_current_pw):
            st.error("❌ Current password is incorrect.")
        elif not r_new_pw or not r_confirm_pw:
            st.error("Please fill in the new password fields.")
        elif r_new_pw != r_confirm_pw:
            st.error("❌ New passwords do not match.")
        else:
            errs = validate_password(r_new_pw)
            if errs:
                st.error("❌ Password requirements not met:")
                for e in errs:
                    st.markdown(f"• {e}")
            elif r_new_pw == r_current_pw:
                st.warning("⚠️ New password must be different from the current one.")
            else:
                new_salt, new_hash = hash_password(r_new_pw)
                users[r_username]["salt"] = new_salt
                users[r_username]["password_hash"] = new_hash
                save_users(users, load_users()[1])

                st.success(f"✅ Password for **{r_username}** has been successfully reset!")
                st.info("You can now login with your new password.")

    st.markdown('</div>', unsafe_allow_html=True)

# Close the main container
st.markdown('</div>', unsafe_allow_html=True)

# Footer
st.markdown("""
<div class="footer">
    © 2026 UKM Management System • Secure Login
</div>
""", unsafe_allow_html=True)

# import streamlit as st
# from pathlib import Path
# import hashlib
# import json
# import secrets
# from datetime import datetime
# import streamlit.components.v1 as components

# # new: central user_data folder
# ROOT = Path(__file__).parent.parent
# USER_DATA_DIR = ROOT / "user_data"
# USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
# DATA_FILE = USER_DATA_DIR / "users.json"

# # ── Also check root users.json ─────────────────────────────────────────────────
# ROOT_USERS_FILE = ROOT / "users.json"

# def load_users():
#     # Try user_data/users.json first, then root users.json
#     for f in (DATA_FILE, ROOT_USERS_FILE):
#         if not f.exists():
#             continue
#         try:
#             raw   = json.loads(f.read_text(encoding="utf-8") or "{}")
#             users = raw.get("users", [])
#             out   = {}
#             for u in users:
#                 if "role" not in u:
#                     u["role"] = "UKM"
#                 out[u["username"]] = u
#             if out:
#                 return out, f
#         except Exception:
#             continue
#     return {}, DATA_FILE

# def save_users(users_dict: dict, filepath: Path):
#     data = {"users": list(users_dict.values())}
#     filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

# def verify_password(stored_salt_hex, stored_hash_hex, password_plain):
#     salt = bytes.fromhex(stored_salt_hex)
#     h = hashlib.pbkdf2_hmac("sha256", password_plain.encode("utf-8"), salt, 100_000)
#     return h.hex() == stored_hash_hex

# def hash_password(password_plain: str) -> tuple[str, str]:
#     """Returns (salt_hex, hash_hex) using pbkdf2_hmac to match login.py."""
#     salt = secrets.token_bytes(16)
#     h    = hashlib.pbkdf2_hmac("sha256", password_plain.encode("utf-8"), salt, 100_000)
#     return salt.hex(), h.hex()

# def validate_password(pw: str) -> list[str]:
#     errors = []
#     if len(pw) < 8:
#         errors.append("At least 8 characters.")
#     if not any(c.isupper() for c in pw):
#         errors.append("At least one uppercase letter.")
#     if not any(c.islower() for c in pw):
#         errors.append("At least one lowercase letter.")
#     if not any(c.isdigit() for c in pw):
#         errors.append("At least one digit.")
#     return errors

# # ══════════════════════════════════════════════════════════════════════════════
# st.set_page_config(page_title="Login", layout="centered")

# st.markdown(
#     """
#     <style>
#     .card {
#       background: #f8fafc;
#       padding: 18px;
#       border-radius: 10px;
#       box-shadow: 0 2px 8px rgba(0,0,0,0.06);
#     }
#     </style>
#     """,
#     unsafe_allow_html=True,
# )

# # ── Already logged in ──────────────────────────────────────────────────────────
# current_user = st.session_state.get("user")
# current_role = st.session_state.get("role")
# if current_user:
#     role_label = f" ({current_role})" if current_role else ""
#     st.success(f"Already logged in as **{current_user}**{role_label}")
#     st.markdown(f"- [Go to your dashboard](/dashboard?user={current_user})")
#     if st.button("Logout"):
#         for k in ("user", "role"):
#             st.session_state.pop(k, None)
#         st.experimental_set_query_params()
#         st.experimental_rerun()
#     st.stop()

# # ══════════════════════════════════════════════════════════════════════════════
# # TABS: Login | Reset Password
# # ══════════════════════════════════════════════════════════════════════════════
# tab_login, tab_reset = st.tabs(["🔐 Login", "🔑 Reset Password"])

# # ─────────────────────────────────────────────────────────────────────────────
# # TAB 1 — Login
# # ─────────────────────────────────────────────────────────────────────────────
# with tab_login:
#     st.title("🔐 Login")

#     with st.container():
#         st.markdown('<div class="card">', unsafe_allow_html=True)
#         username  = st.text_input("Username", key="login_username")
#         password  = st.text_input("Password", type="password", key="login_password")
#         submitted = st.button("Login", use_container_width=True)
#         st.markdown('</div>', unsafe_allow_html=True)

#     if submitted:
#         users, _ = load_users()
#         user     = users.get(username)
#         if not user:
#             st.error("❌ User not found.")
#             st.info("💡 If you forgot your password, use the **Reset Password** tab above.")
#         else:
#             ok = verify_password(user["salt"], user["password_hash"], password)
#             if ok:
#                 st.session_state["user"] = username
#                 st.session_state["role"] = user.get("role", "UKM")
#                 st.experimental_set_query_params(user=username)
#                 components.html(
#                     f"<script>window.location.href='/dashboard?user={username}';</script>",
#                     height=0,
#                 )
#                 st.stop()
#             else:
#                 st.error("❌ Invalid password.")
#                 st.info("💡 Forgot your password? Use the **Reset Password** tab above.")

# # ─────────────────────────────────────────────────────────────────────────────
# # TAB 2 — Reset Password (self-service, no email — verify username + old pw)
# # ─────────────────────────────────────────────────────────────────────────────
# with tab_reset:
#     st.title("🔑 Reset Password")
#     st.caption("Enter your username and current password, then choose a new one.")

#     with st.form("reset_form", clear_on_submit=True):
#         r_username   = st.text_input("Username")
#         r_current_pw = st.text_input("Current password",     type="password")
#         r_new_pw     = st.text_input("New password",         type="password")
#         r_confirm_pw = st.text_input("Confirm new password", type="password")

#         st.caption(
#             "New password must be ≥ 8 characters with uppercase, lowercase, and a digit."
#         )

#         reset_btn = st.form_submit_button("🔄 Reset Password", use_container_width=True)

#     if reset_btn:
#         users, users_file = load_users()

#         if not r_username:
#             st.warning("Please enter your username.")
#         elif r_username not in users:
#             st.error(f"❌ Username `{r_username}` not found.")
#         elif not r_current_pw:
#             st.warning("Please enter your current password.")
#         elif not verify_password(users[r_username]["salt"], users[r_username]["password_hash"], r_current_pw):
#             st.error("❌ Current password is incorrect.")
#         elif not r_new_pw:
#             st.warning("Please enter a new password.")
#         elif r_new_pw != r_confirm_pw:
#             st.error("❌ New passwords do not match.")
#         else:
#             errs = validate_password(r_new_pw)
#             if errs:
#                 st.error("❌ Password requirements not met:")
#                 for e in errs:
#                     st.markdown(f"- {e}")
#             elif r_new_pw == r_current_pw:
#                 st.warning("⚠️ New password must differ from the current one.")
#             else:
#                 new_salt, new_hash                  = hash_password(r_new_pw)
#                 users[r_username]["salt"]           = new_salt
#                 users[r_username]["password_hash"]  = new_hash
#                 save_users(users, users_file)
#                 st.success(f"✅ Password for `{r_username}` has been reset. Please log in.")

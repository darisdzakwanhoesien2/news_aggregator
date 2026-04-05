import streamlit as st
from pathlib import Path
import hashlib
import json
import secrets
from datetime import datetime
import streamlit.components.v1 as components

# new: central user_data folder
ROOT = Path(__file__).parent.parent
USER_DATA_DIR = ROOT / "user_data"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = USER_DATA_DIR / "users.json"

# ── Also check root users.json ─────────────────────────────────────────────────
ROOT_USERS_FILE = ROOT / "users.json"

def load_users():
    # Try user_data/users.json first, then root users.json
    for f in (DATA_FILE, ROOT_USERS_FILE):
        if not f.exists():
            continue
        try:
            raw   = json.loads(f.read_text(encoding="utf-8") or "{}")
            users = raw.get("users", [])
            out   = {}
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
    """Returns (salt_hex, hash_hex) using pbkdf2_hmac to match login.py."""
    salt = secrets.token_bytes(16)
    h    = hashlib.pbkdf2_hmac("sha256", password_plain.encode("utf-8"), salt, 100_000)
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

# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="Login", layout="centered")

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

# ── Already logged in ──────────────────────────────────────────────────────────
current_user = st.session_state.get("user")
current_role = st.session_state.get("role")
if current_user:
    role_label = f" ({current_role})" if current_role else ""
    st.success(f"Already logged in as **{current_user}**{role_label}")
    st.markdown(f"- [Go to your dashboard](/dashboard?user={current_user})")
    if st.button("Logout"):
        for k in ("user", "role"):
            st.session_state.pop(k, None)
        st.experimental_set_query_params()
        st.experimental_rerun()
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# TABS: Login | Reset Password
# ══════════════════════════════════════════════════════════════════════════════
tab_login, tab_reset = st.tabs(["🔐 Login", "🔑 Reset Password"])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — Login
# ─────────────────────────────────────────────────────────────────────────────
with tab_login:
    st.title("🔐 Login")

    with st.container():
        st.markdown('<div class="card">', unsafe_allow_html=True)
        username  = st.text_input("Username", key="login_username")
        password  = st.text_input("Password", type="password", key="login_password")
        submitted = st.button("Login", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    if submitted:
        users, _ = load_users()
        user     = users.get(username)
        if not user:
            st.error("❌ User not found.")
            st.info("💡 If you forgot your password, use the **Reset Password** tab above.")
        else:
            ok = verify_password(user["salt"], user["password_hash"], password)
            if ok:
                st.session_state["user"] = username
                st.session_state["role"] = user.get("role", "UKM")
                st.experimental_set_query_params(user=username)
                components.html(
                    f"<script>window.location.href='/dashboard?user={username}';</script>",
                    height=0,
                )
                st.stop()
            else:
                st.error("❌ Invalid password.")
                st.info("💡 Forgot your password? Use the **Reset Password** tab above.")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — Reset Password (self-service, no email — verify username + old pw)
# ─────────────────────────────────────────────────────────────────────────────
with tab_reset:
    st.title("🔑 Reset Password")
    st.caption("Enter your username and current password, then choose a new one.")

    with st.form("reset_form", clear_on_submit=True):
        r_username   = st.text_input("Username")
        r_current_pw = st.text_input("Current password",     type="password")
        r_new_pw     = st.text_input("New password",         type="password")
        r_confirm_pw = st.text_input("Confirm new password", type="password")

        st.caption(
            "New password must be ≥ 8 characters with uppercase, lowercase, and a digit."
        )

        reset_btn = st.form_submit_button("🔄 Reset Password", use_container_width=True)

    if reset_btn:
        users, users_file = load_users()

        if not r_username:
            st.warning("Please enter your username.")
        elif r_username not in users:
            st.error(f"❌ Username `{r_username}` not found.")
        elif not r_current_pw:
            st.warning("Please enter your current password.")
        elif not verify_password(users[r_username]["salt"], users[r_username]["password_hash"], r_current_pw):
            st.error("❌ Current password is incorrect.")
        elif not r_new_pw:
            st.warning("Please enter a new password.")
        elif r_new_pw != r_confirm_pw:
            st.error("❌ New passwords do not match.")
        else:
            errs = validate_password(r_new_pw)
            if errs:
                st.error("❌ Password requirements not met:")
                for e in errs:
                    st.markdown(f"- {e}")
            elif r_new_pw == r_current_pw:
                st.warning("⚠️ New password must differ from the current one.")
            else:
                new_salt, new_hash                  = hash_password(r_new_pw)
                users[r_username]["salt"]           = new_salt
                users[r_username]["password_hash"]  = new_hash
                save_users(users, users_file)
                st.success(f"✅ Password for `{r_username}` has been reset. Please log in.")
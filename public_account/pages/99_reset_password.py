"""
────────────────────────────────────────────────────────────────────────────────
Reset Password Page
────────────────────────────────────────────────────────────────────────────────
"""

import hashlib
import json
import os
import secrets
from pathlib import Path

import streamlit as st

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Reset Password",
    page_icon="🔑",
    layout="centered",
)

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parents[1]
USERS_FILE = BASE_DIR / "users.json"


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _load_users() -> dict:
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"users": []}


def _save_users(data: dict) -> None:
    USERS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def _find_user(users: list[dict], username: str) -> tuple[int, dict | None]:
    for i, u in enumerate(users):
        if u.get("username", "").lower() == username.lower():
            return i, u
    return -1, None


def _verify_current_password(user: dict, password: str) -> bool:
    salt      = user.get("salt", "")
    pw_hash   = user.get("password_hash", "")
    return _hash_password(password, salt) == pw_hash


def _update_password(username: str, new_password: str) -> bool:
    data  = _load_users()
    users = data.get("users", [])
    idx, user = _find_user(users, username)
    if user is None:
        return False
    new_salt                     = secrets.token_hex(16)
    users[idx]["salt"]           = new_salt
    users[idx]["password_hash"]  = _hash_password(new_password, new_salt)
    data["users"]                = users
    _save_users(data)
    return True


def _validate_new_password(password: str) -> list[str]:
    """Return list of validation error strings (empty = valid)."""
    errors = []
    if len(password) < 8:
        errors.append("At least 8 characters long.")
    if not any(c.isupper() for c in password):
        errors.append("At least one uppercase letter.")
    if not any(c.islower() for c in password):
        errors.append("At least one lowercase letter.")
    if not any(c.isdigit() for c in password):
        errors.append("At least one digit.")
    return errors


def _resolve_logged_in_user() -> str | None:
    """Try to get the currently logged-in user from session state."""
    for key in ("username", "user", "current_user", "logged_in_user"):
        val = st.session_state.get(key)
        if val and isinstance(val, str):
            return val
    return None


# ══════════════════════════════════════════════════════════════════════════════
# UI
# ══════════════════════════════════════════════════════════════════════════════

st.title("🔑 Reset Password")
st.caption("Change your account password securely.")

current_user = _resolve_logged_in_user()

tab_self, tab_admin = st.tabs(["🙋 Change My Password", "🛡️ Admin Reset"])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — Self-service (must be logged in)
# ─────────────────────────────────────────────────────────────────────────────
with tab_self:
    if not current_user:
        st.warning("⚠️ You must be logged in to change your password.")
        st.info("Please log in via the main page first.")
        st.stop()

    st.subheader(f"Changing password for: `{current_user}`")

    with st.form("self_reset_form", clear_on_submit=True):
        current_pw  = st.text_input("Current password",     type="password")
        new_pw      = st.text_input("New password",         type="password")
        confirm_pw  = st.text_input("Confirm new password", type="password")

        # Live strength hints (outside form widgets can't update, so show static guide)
        st.caption(
            "Password must be ≥ 8 characters and contain uppercase, "
            "lowercase, and at least one digit."
        )

        submitted = st.form_submit_button("🔄 Update Password", use_container_width=True)

    if submitted:
        # Load & verify
        data  = _load_users()
        _, user = _find_user(data.get("users", []), current_user)

        if user is None:
            st.error("User not found. Please contact an administrator.")
        elif not current_pw:
            st.warning("Please enter your current password.")
        elif not _verify_current_password(user, current_pw):
            st.error("❌ Current password is incorrect.")
        elif not new_pw:
            st.warning("Please enter a new password.")
        elif new_pw != confirm_pw:
            st.error("❌ New passwords do not match.")
        else:
            errors = _validate_new_password(new_pw)
            if errors:
                st.error("❌ Password does not meet requirements:")
                for e in errors:
                    st.markdown(f"- {e}")
            elif new_pw == current_pw:
                st.warning("⚠️ New password must differ from the current password.")
            else:
                ok = _update_password(current_user, new_pw)
                if ok:
                    st.success("✅ Password updated successfully!")
                else:
                    st.error("Failed to save new password. Please try again.")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — Admin reset (must be logged in as admin/Bank role)
# ─────────────────────────────────────────────────────────────────────────────
with tab_admin:
    # Determine if current user has admin rights
    admin_roles = {"admin", "bank"}
    current_role = ""

    if current_user:
        data = _load_users()
        _, admin_user = _find_user(data.get("users", []), current_user)
        current_role = (admin_user or {}).get("role", "").lower()

    if not current_user or current_role not in admin_roles:
        st.warning("🔒 This section is restricted to **Bank** or **Admin** accounts.")
        st.stop()

    st.subheader("Admin: Reset Any User's Password")
    st.caption("Select a user and set a temporary password for them.")

    data  = _load_users()
    users = data.get("users", [])

    # Build display options (exclude self)
    user_options = [
        u["username"]
        for u in users
        if u.get("username", "").lower() != (current_user or "").lower()
    ]

    if not user_options:
        st.info("No other users found.")
        st.stop()

    with st.form("admin_reset_form", clear_on_submit=True):
        target_username = st.selectbox("Select user to reset", user_options)

        # Show target user info
        _, target_user = _find_user(users, target_username)
        if target_user:
            st.markdown(
                f"**Role:** `{target_user.get('role', '—')}` &nbsp;|&nbsp; "
                f"**Created:** `{target_user.get('created_at', '—')[:10]}`"
            )

        new_pw     = st.text_input("New temporary password", type="password")
        confirm_pw = st.text_input("Confirm password",       type="password")
        admin_pw   = st.text_input(
            "Your admin password (for confirmation)", type="password"
        )

        submitted = st.form_submit_button("🔄 Reset User Password", use_container_width=True)

    if submitted:
        # Re-load fresh copy
        data = _load_users()
        _, admin_u = _find_user(data.get("users", []), current_user)

        if admin_u is None:
            st.error("Admin user not found.")
        elif not _verify_current_password(admin_u, admin_pw):
            st.error("❌ Admin password confirmation failed.")
        elif not new_pw:
            st.warning("Please enter a new password.")
        elif new_pw != confirm_pw:
            st.error("❌ Passwords do not match.")
        else:
            errors = _validate_new_password(new_pw)
            if errors:
                st.error("❌ Password does not meet requirements:")
                for e in errors:
                    st.markdown(f"- {e}")
            else:
                ok = _update_password(target_username, new_pw)
                if ok:
                    st.success(f"✅ Password for `{target_username}` has been reset.")
                else:
                    st.error("Failed to save. Please try again.")
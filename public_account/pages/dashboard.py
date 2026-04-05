import streamlit as st
from pathlib import Path
import json
from datetime import datetime

# new: central user_data folder
ROOT = Path(__file__).parent.parent
USER_DATA_DIR = ROOT / "user_data"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = USER_DATA_DIR / "users.json"

def load_users_list():
    if not DATA_FILE.exists():
        return []
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8") or "{}")
        return raw.get("users", [])
    except Exception:
        return []

def save_users_list(users_list):
    DATA_FILE.write_text(json.dumps({"users": users_list}, indent=2), encoding="utf-8")

def load_users_map(migrate=True):
    """
    Return {username: userdict}. If migrate=True, ensure every user has a 'role'
    and persist that change back to disk (single-shot).
    """
    users = load_users_list()
    out = {}
    changed = False
    for u in users:
        if "role" not in u:
            u["role"] = "UKM"
            changed = True
        out[u["username"]] = u
    if migrate and changed:
        try:
            save_users_list(users)
        except Exception:
            pass
    return out

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
    .role { font-weight:600; padding:4px 8px; border-radius:6px; display:inline-block; margin-left:8px; }
    .role-UKM { background:#ecfdf5; color:#065f46; }
    .role-Supplier { background:#fffbeb; color:#7c2d12; }
    .role-Bank { background:#eef2ff; color:#3730a3; }
    .small { font-size:12px; color:#6b7280; }
    </style>
    """,
    unsafe_allow_html=True,
)

# determine current user and role (rehydrate from query params if needed)
user_key = st.session_state.get("user")
if not user_key:
    params = st.experimental_get_query_params()
    if "user" in params and params["user"]:
        st.session_state["user"] = params["user"][0]
        user_key = st.session_state.get("user")

if not user_key:
    st.warning("You are not logged in. Please login first.")
    st.markdown("- [Go to Login](/login)")
    st.stop()

# load users and perform one-time migration to add missing roles
users = load_users_map(migrate=True)
user = users.get(user_key, {})
role = st.session_state.get("role") or user.get("role", "UKM")

with st.container():
    st.markdown('<div class="card">', unsafe_allow_html=True)
    # render greeting + role badge using markdown (supports unsafe HTML)
    badge_html = f"<span class='role role-{role}'>{role}</span>"
    st.markdown(f"### Hello, {user_key} {badge_html}", unsafe_allow_html=True)

    created = user.get("created_at", "Unknown")
    st.markdown(f"- <span class='small'>Account created:</span> {created}", unsafe_allow_html=True)
    st.markdown(f"- <span class='small'>Username:</span> {user_key}", unsafe_allow_html=True)
    st.markdown('<div class="muted">This is your personal dashboard. Capabilities depend on your role.</div>', unsafe_allow_html=True)

    st.markdown("---")
    # Allow the current user to change their own role (local app convenience)
    st.markdown("#### My role")
    new_role = st.selectbox("Select role", options=["UKM", "Supplier", "Bank"], index=["UKM","Supplier","Bank"].index(role))
    if st.button("Save role"):
        users_list = load_users_list()
        updated = False
        for rec in users_list:
            if rec.get("username") == user_key:
                rec["role"] = new_role
                updated = True
                break
        if updated:
            try:
                save_users_list(users_list)
                st.session_state["role"] = new_role
                role = new_role
                st.success(f"Role updated to {new_role}")
                # refresh local users map
                users = load_users_map(migrate=False)
            except Exception as e:
                st.error(f"Failed to save role: {e}")
        else:
            st.error("Could not find your user record to update.")

    st.markdown("---")

    # Role-specific UI
    if role == "UKM":
        st.markdown("### ✅ UKM actions")
        st.info("As a UKM you can fill in your profile/form and submit answers.")
        if st.button("✏️ Fill Profile / Form (placeholder)"):
            st.info("Opening the UKM form... (implement your form page and navigate here)")
        st.markdown("---")
        st.markdown("Your recent submissions / verifications will appear here (not implemented).")

    elif role in ("Supplier", "Bank"):
        st.markdown("### 🔎 Supplier / Bank dashboard")
        st.info("You can browse UKM profiles and view scores submitted by UKMs.")
        # show list of UKM users
        ukm_users = [u for u in users.values() if u.get("role") == "UKM"]
        if ukm_users:
            df = pd.DataFrame([
                {"username": u["username"], "created_at": u.get("created_at",""), "note": u.get("note","")}
                for u in ukm_users
            ])
            st.dataframe(df)
            sel = st.selectbox("Select a UKM to view details", options=[u["username"] for u in ukm_users])
            if sel:
                st.markdown(f"#### Details for {sel}")
                sel_user = users.get(sel, {})
                st.json({k: v for k, v in sel_user.items() if k not in ("salt","password_hash")})
        else:
            st.info("No UKM users found in the user database.")

    else:
        st.info("Unknown role. Contact admin.")

    if st.button("Logout"):
        if "user" in st.session_state:
            del st.session_state["user"]
        if "role" in st.session_state:
            del st.session_state["role"]
        st.experimental_set_query_params()  # clear url param
        st.success("Logged out.")
        st.experimental_rerun()

    st.markdown('</div>', unsafe_allow_html=True)
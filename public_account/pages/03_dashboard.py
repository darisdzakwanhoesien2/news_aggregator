import streamlit as st
from pathlib import Path
import json
from datetime import datetime
import pandas as pd
from streamlit_compat import get_query_params, set_query_params

# ====================== CONFIGURATION ======================
ROOT = Path(__file__).parent.parent
USER_DATA_DIR = ROOT / "user_data"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = USER_DATA_DIR / "users.json"

# ====================== HELPER FUNCTIONS ======================
def load_users_list():
    if not DATA_FILE.exists():
        return []
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8") or "{}")
        return raw.get("users", [])
    except Exception:
        return []

def save_users_list(users_list):
    DATA_FILE.write_text(json.dumps({"users": users_list}, indent=2, ensure_ascii=False), encoding="utf-8")

def load_users_map(migrate=True):
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

# ====================== PAGE CONFIG ======================
st.set_page_config(
    page_title="Dashboard • UKM System",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ====================== CUSTOM CSS ======================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    .main {
        background: linear-gradient(135deg, #f8fafc 0%, #e0e7ff 100%);
    }

    .dashboard-container {
        max-width: 1200px;
        margin: 30px auto;
        background: white;
        border-radius: 20px;
        box-shadow: 0 20px 40px rgba(0, 0, 0, 0.08);
        overflow: hidden;
    }

    .header {
        background: linear-gradient(135deg, #4f46e5, #7c3aed);
        color: white;
        padding: 40px 40px 30px 40px;
    }

    .header h1 {
        margin: 0;
        font-size: 32px;
        font-weight: 700;
    }

    .header p {
        margin: 8px 0 0 0;
        opacity: 0.9;
        font-size: 16px;
    }

    .content {
        padding: 40px;
    }

    .card {
        background: #ffffff;
        padding: 24px;
        border-radius: 16px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 4px 15px rgba(0,0,0,0.04);
        margin-bottom: 24px;
    }

    .role-badge {
        font-weight: 600;
        padding: 6px 14px;
        border-radius: 30px;
        font-size: 14px;
        display: inline-block;
    }

    .role-UKM { background:#ecfdf5; color:#065f46; }
    .role-Supplier { background:#fffbeb; color:#7c2d12; }
    .role-Bank { background:#eef2ff; color:#3730a3; }

    .stButton > button {
        border-radius: 12px;
        height: 48px;
        font-weight: 600;
        transition: all 0.3s ease;
    }

    .stButton > button:hover {
        transform: translateY(-2px);
    }

    .metric-card {
        background: #f8fafc;
        padding: 20px;
        border-radius: 14px;
        text-align: center;
        border: 1px solid #e2e8f0;
    }
</style>
""", unsafe_allow_html=True)

# ====================== AUTH CHECK ======================
user_key = st.session_state.get("user")
if not user_key:
    params = get_query_params()
    if "user" in params and params["user"]:
        st.session_state["user"] = params["user"][0]
        user_key = st.session_state.get("user")

if not user_key:
    st.error("You are not logged in.")
    st.markdown("[Go to Login](/login)")
    st.stop()

# Load user data
users = load_users_map(migrate=True)
user = users.get(user_key, {})
role = st.session_state.get("role") or user.get("role", "UKM")

# ====================== HEADER ======================
st.markdown(f"""
<div class="dashboard-container">
    <div class="header">
        <h1>👤 Welcome back, {user_key}!</h1>
        <p>Role: <span class="role-badge role-{role}">{role}</span></p>
    </div>
    <div class="content">
""", unsafe_allow_html=True)

# ====================== MAIN CONTENT ======================
col1, col2 = st.columns([3, 1])

with col1:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(f"### Account Information")
    st.markdown(f"**Username:** {user_key}")
    st.markdown(f"**Role:** <span class='role-badge role-{role}'>{role}</span>", unsafe_allow_html=True)
    
    created = user.get("created_at", "Unknown")
    if created != "Unknown":
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            created_str = dt.strftime("%d %B %Y")
        except:
            created_str = created
    else:
        created_str = "Unknown"
    
    st.markdown(f"**Account created:** {created_str}")
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="card metric-card">', unsafe_allow_html=True)
    st.metric("Current Role", role)
    st.markdown('</div>', unsafe_allow_html=True)

# Role Change Section
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown("#### Change My Role")
new_role = st.selectbox(
    "Select new role",
    options=["UKM", "Supplier", "Bank"],
    index=["UKM", "Supplier", "Bank"].index(role)
)

if st.button("Save Role Change", use_container_width=True, type="primary"):
    users_list = load_users_list()
    updated = False
    for rec in users_list:
        if rec.get("username") == user_key:
            rec["role"] = new_role
            updated = True
            break
    if updated:
        save_users_list(users_list)
        st.session_state["role"] = new_role
        st.success(f"✅ Role successfully updated to **{new_role}**")
        st.experimental_rerun()
    else:
        st.error("Failed to update role.")

st.markdown('</div>', unsafe_allow_html=True)

# ====================== ROLE-SPECIFIC DASHBOARD ======================
st.markdown('<div class="card">', unsafe_allow_html=True)

if role == "UKM":
    st.markdown("### ✅ UKM Dashboard")
    st.info("As a UKM, you can fill in your profile, submit forms, and track your verification results.")
    
    if st.button("✏️ Fill Profile / Form", use_container_width=True, type="primary"):
        st.info("UKM Form page will be opened here (link to your form page).")
    
    st.markdown("Your submitted forms and verification history will appear below.")

elif role in ("Supplier", "Bank"):
    st.markdown("### 🔎 Supplier / Bank Dashboard")
    st.info("You can browse all UKM profiles and view their submitted data.")
    
    ukm_users = [u for u in users.values() if u.get("role") == "UKM"]
    
    if ukm_users:
        st.subheader(f"Registered UKMs ({len(ukm_users)})")
        df = pd.DataFrame([
            {
                "Username": u["username"],
                "Created": u.get("created_at", "")[:10],
                "Role": u.get("role", "")
            }
            for u in ukm_users
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        sel = st.selectbox("Select a UKM to view details", options=[u["username"] for u in ukm_users])
        if sel:
            st.markdown(f"#### Details for **{sel}**")
            sel_user = users.get(sel, {})
            clean_data = {k: v for k, v in sel_user.items() if k not in ("salt", "password_hash")}
            st.json(clean_data)
    else:
        st.info("No UKM users found yet.")

else:
    st.info("Unknown role detected.")

st.markdown('</div>', unsafe_allow_html=True)

# ====================== VERIFICATION RESULTS SECTION ======================
st.markdown("---")
st.subheader("📊 My Verification Results")

def load_user_results(username: str) -> pd.DataFrame:
    results = []
    user_sessions = USER_DATA_DIR / username / "sessions"
    if not user_sessions.exists():
        return pd.DataFrame()
    for s in sorted(user_sessions.iterdir()):
        out_f = s / "outputs" / "verification.json"
        if out_f.exists():
            try:
                j = json.loads(out_f.read_text(encoding="utf-8"))
                j["_session"] = s.name
                results.append(j)
            except Exception:
                continue
    return pd.DataFrame(results)

user_df = load_user_results(user_key)

if user_df.empty:
    st.info("No verification results found yet. Submit some forms to see data here.")
else:
    user_df["timestamp"] = pd.to_datetime(user_df.get("timestamp"), errors="coerce")
    user_df = user_df.sort_values("timestamp", ascending=False)
    
    latest = user_df.iloc[0]
    st.metric("Latest Verification Score", f"{latest.get('pct_verified', 0)}%")

    # Charts
    chart_df = user_df.set_index("timestamp")
    if "pct_verified" in chart_df.columns:
        st.line_chart(chart_df["pct_verified"], use_container_width=True)
    
    st.subheader("Recent Sessions")
    table_cols = ["_session", "company", "pct_verified", "total_final_score", "timestamp"]
    present = [c for c in table_cols if c in user_df.columns]
    st.dataframe(user_df[present], use_container_width=True, hide_index=True)

    st.download_button(
        "⬇️ Download My Results (CSV)",
        data=user_df.to_csv(index=False),
        file_name=f"{user_key}_results_{datetime.utcnow().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True
    )

# ====================== LOGOUT ======================
if st.button("🚪 Logout", use_container_width=True):
    for key in ["user", "role"]:
        if key in st.session_state:
            del st.session_state[key]
    set_query_params()
    st.success("You have been logged out.")
    st.experimental_rerun()

# Close main container
st.markdown('</div></div>', unsafe_allow_html=True)

# Footer
st.markdown("""
<div style="text-align:center; margin:40px 0; color:#64748b; font-size:14px;">
    © 2026 UKM Management System • Secure Dashboard
</div>
""", unsafe_allow_html=True)

# import streamlit as st
# from pathlib import Path
# import json
# from datetime import datetime
# import pandas as pd

# ROOT         = Path(__file__).parent.parent
# USER_DATA_DIR = ROOT / "user_data"
# USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
# DATA_FILE    = USER_DATA_DIR / "users.json"

# def load_users_list():
#     if not DATA_FILE.exists():
#         return []
#     try:
#         raw = json.loads(DATA_FILE.read_text(encoding="utf-8") or "{}")
#         return raw.get("users", [])
#     except Exception:
#         return []

# def save_users_list(users_list):
#     DATA_FILE.write_text(json.dumps({"users": users_list}, indent=2), encoding="utf-8")

# def load_users_map(migrate=True):
#     """
#     Return {username: userdict}. If migrate=True, ensure every user has a 'role'
#     and persist that change back to disk (single-shot).
#     """
#     users = load_users_list()
#     out = {}
#     changed = False
#     for u in users:
#         if "role" not in u:
#             u["role"] = "UKM"
#             changed = True
#         out[u["username"]] = u
#     if migrate and changed:
#         try:
#             save_users_list(users)
#         except Exception:
#             pass
#     return out

# st.set_page_config(page_title="Personal Page", layout="centered")
# st.title("👤 Personal Page / Dashboard")

# st.markdown(
#     """
#     <style>
#     .card {
#       background: #ffffff;
#       padding: 18px;
#       border-radius: 10px;
#       border: 1px solid #e6eef8;
#       box-shadow: 0 1px 6px rgba(0,0,0,0.04);
#     }
#     .muted { color: #6b7280; font-size:12px; }
#     .role { font-weight:600; padding:4px 8px; border-radius:6px; display:inline-block; margin-left:8px; }
#     .role-UKM { background:#ecfdf5; color:#065f46; }
#     .role-Supplier { background:#fffbeb; color:#7c2d12; }
#     .role-Bank { background:#eef2ff; color:#3730a3; }
#     .small { font-size:12px; color:#6b7280; }
#     </style>
#     """,
#     unsafe_allow_html=True,
# )

# # determine current user and role (rehydrate from query params if needed)
# user_key = st.session_state.get("user")
# if not user_key:
#     params = st.experimental_get_query_params()
#     if "user" in params and params["user"]:
#         st.session_state["user"] = params["user"][0]
#         user_key = st.session_state.get("user")

# if not user_key:
#     st.warning("You are not logged in. Please login first.")
#     st.markdown("- [Go to Login](/login)")
#     st.stop()

# # load users and perform one-time migration to add missing roles
# users = load_users_map(migrate=True)
# user = users.get(user_key, {})
# role = st.session_state.get("role") or user.get("role", "UKM")

# with st.container():
#     st.markdown('<div class="card">', unsafe_allow_html=True)
#     # render greeting + role badge using markdown (supports unsafe HTML)
#     badge_html = f"<span class='role role-{role}'>{role}</span>"
#     st.markdown(f"### Hello, {user_key} {badge_html}", unsafe_allow_html=True)

#     created = user.get("created_at", "Unknown")
#     st.markdown(f"- <span class='small'>Account created:</span> {created}", unsafe_allow_html=True)
#     st.markdown(f"- <span class='small'>Username:</span> {user_key}", unsafe_allow_html=True)
#     st.markdown('<div class="muted">This is your personal dashboard. Capabilities depend on your role.</div>', unsafe_allow_html=True)

#     st.markdown("---")
#     # Allow the current user to change their own role (local app convenience)
#     st.markdown("#### My role")
#     new_role = st.selectbox("Select role", options=["UKM", "Supplier", "Bank"], index=["UKM","Supplier","Bank"].index(role))
#     if st.button("Save role"):
#         users_list = load_users_list()
#         updated = False
#         for rec in users_list:
#             if rec.get("username") == user_key:
#                 rec["role"] = new_role
#                 updated = True
#                 break
#         if updated:
#             try:
#                 save_users_list(users_list)
#                 st.session_state["role"] = new_role
#                 role = new_role
#                 st.success(f"Role updated to {new_role}")
#                 # refresh local users map
#                 users = load_users_map(migrate=False)
#             except Exception as e:
#                 st.error(f"Failed to save role: {e}")
#         else:
#             st.error("Could not find your user record to update.")

#     st.markdown("---")

#     # Role-specific UI
#     if role == "UKM":
#         st.markdown("### ✅ UKM actions")
#         st.info("As a UKM you can fill in your profile/form and submit answers.")
#         if st.button("✏️ Fill Profile / Form (placeholder)"):
#             st.info("Opening the UKM form... (implement your form page and navigate here)")
#         st.markdown("---")
#         st.markdown("Your recent submissions / verifications will appear here (not implemented).")

#     elif role in ("Supplier", "Bank"):
#         st.markdown("### 🔎 Supplier / Bank dashboard")
#         st.info("You can browse UKM profiles and view scores submitted by UKMs.")
#         # show list of UKM users
#         ukm_users = [u for u in users.values() if u.get("role") == "UKM"]
#         if ukm_users:
#             df = pd.DataFrame([
#                 {"username": u["username"], "created_at": u.get("created_at",""), "note": u.get("note","")}
#                 for u in ukm_users
#             ])
#             st.dataframe(df)
#             sel = st.selectbox("Select a UKM to view details", options=[u["username"] for u in ukm_users])
#             if sel:
#                 st.markdown(f"#### Details for {sel}")
#                 sel_user = users.get(sel, {})
#                 st.json({k: v for k, v in sel_user.items() if k not in ("salt","password_hash")})
#         else:
#             st.info("No UKM users found in the user database.")

#     else:
#         st.info("Unknown role. Contact admin.")

#     # --------------------
#     # User-specific visualizations (after login)
#     # --------------------
#     def load_user_results(username: str) -> pd.DataFrame:
#         results = []
#         user_sessions = USER_DATA_DIR / username / "sessions"
#         if not user_sessions.exists():
#             return pd.DataFrame()
#         for s in sorted(user_sessions.iterdir()):
#             out_f = s / "outputs" / "verification.json"
#             if out_f.exists():
#                 try:
#                     j = json.loads(out_f.read_text(encoding="utf-8"))
#                     j["_session"] = s.name
#                     results.append(j)
#                 except Exception:
#                     continue
#         if not results:
#             return pd.DataFrame()
#         return pd.DataFrame(results)

#     st.markdown("---")
#     st.subheader("📊 My Verification Results")
#     user_df = load_user_results(user_key)
#     if user_df.empty:
#         st.info("No verification results found for your account yet.")
#     else:
#         user_df["timestamp"] = pd.to_datetime(user_df.get("timestamp"), errors="coerce")
#         user_df = user_df.sort_values("timestamp")
#         latest  = user_df.iloc[-1]
#         st.metric("Latest % Verified", f"{latest.get('pct_verified', 0)}%")

#         chart_df = user_df.set_index("timestamp")
#         if "pct_verified" in chart_df.columns:
#             st.line_chart(chart_df["pct_verified"])
#         if "total_final_score" in chart_df.columns:
#             st.bar_chart(chart_df["total_final_score"])

#         st.divider()
#         st.subheader("Session table")
#         table_cols = ["_session","session_id","company","pct_verified","total_final_score","model","timestamp"]
#         present    = [c for c in table_cols if c in user_df.columns]
#         st.dataframe(user_df[present].sort_values("timestamp", ascending=False), use_container_width=True)
#         st.download_button(
#             "⬇️ Download my results CSV",
#             data=user_df.to_csv(index=False),
#             file_name=f"{user_key}_verification_results_{datetime.utcnow().strftime('%Y%m%d')}.csv",
#             mime="text/csv",
#         )

#         st.markdown("### 🔗 Quick access — View session details")

#         for _, row in user_df.sort_values("timestamp", ascending=False).iterrows():
#             sess_name = str(row.get("_session") or row.get("session_id") or "")
#             company   = row.get("company", "")
#             pct       = row.get("pct_verified", "")
#             ts        = row.get("timestamp", "")

#             c1, c2, c3 = st.columns([5, 1, 1])
#             c1.markdown(f"**{sess_name}** — {company}  \n<span style='font-size:11px;color:#6b7280'>{ts}</span>", unsafe_allow_html=True)
#             c2.markdown(f"**{pct}%**")

#             btn_key = f"view_{user_key}_{sess_name}"
#             if c3.button("📄 View", key=btn_key):
#                 ver_path = USER_DATA_DIR / user_key / "sessions" / sess_name / "outputs" / "verification.json"
#                 if not ver_path.exists():
#                     st.error(f"Results file not found:\n`{ver_path}`")
#                 else:
#                     try:
#                         j = json.loads(ver_path.read_text(encoding="utf-8"))
#                         # ✅ Store full result payload in session_state
#                         st.session_state["_result_json"]     = j
#                         st.session_state["_result_user"]     = user_key
#                         st.session_state["_result_sess"]     = sess_name
#                         # ✅ Use st.switch_page — correct Streamlit ≥1.31 navigation API
#                         st.switch_page("pages/05_results.py")
#                     except Exception as e:
#                         st.error(f"Failed to load results: {e}")

#     if st.button("Logout"):
#         if "user" in st.session_state:
#             del st.session_state["user"]
#         if "role" in st.session_state:
#             del st.session_state["role"]
#         st.experimental_set_query_params()  # clear url param
#         st.success("Logged out.")
#         st.experimental_rerun()

#     st.markdown('</div>', unsafe_allow_html=True)

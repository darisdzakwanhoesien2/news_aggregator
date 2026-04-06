import streamlit as st
from pathlib import Path

st.set_page_config(page_title="Public Account", layout="centered")

# New: polished HTML + CSS header/card layout
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
body { font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, Arial; }
.app-card {
  max-width: 920px; margin: 18px auto; padding: 20px; border-radius: 12px;
  background: linear-gradient(180deg,#ffffff,#fbfdff);
  border: 1px solid #e6eef8; box-shadow: 0 8px 30px rgba(15,23,42,0.04);
}
.header-row { display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
.logo {
  width:64px; height:64px; display:flex; align-items:center; justify-content:center;
  border-radius:12px; background:linear-gradient(90deg,#2563eb,#7c3aed); color:white; font-weight:800;
  font-size:22px;
}
.h1 { margin:0; font-size:20px; font-weight:800; color:#0f172a; }
.lead { margin:6px 0 0; color:#6b7280; font-size:13px; }
.links { display:flex; gap:10px; flex-wrap:wrap; margin-top:12px; }
.link-btn {
  display:inline-block; padding:10px 14px; border-radius:10px; text-decoration:none; color:#0f172a;
  background: #f8fafc; border:1px solid #e6eef8; font-weight:600; font-size:14px;
}
.link-primary {
  background: linear-gradient(90deg,#2563eb,#7c3aed); color:white; border:none;
  box-shadow: 0 6px 18px rgba(37,99,235,0.12);
}
.user-pill { padding:6px 10px; border-radius:999px; background:#eef2ff; color:#3730a3; font-weight:700; font-size:13px; }
.small { font-size:12px; color:#6b7280; margin-top:8px; }
.footer-note { margin-top:14px; font-size:12px; color:#9aa4b2; }
</style>
"""

base = Path(__file__).parent
login_page = "/login"
register_page = "/register"
user = st.session_state.get("user")
# if a user is logged in, include the query param so navigation keeps the session
profile_page = f"/dashboard?user={user}" if user else "/dashboard"

html = f"""
{CSS}
<div class="app-card">
  <div class="header-row">
    <div class="logo">PA</div>
    <div style="flex:1">
      <div class="h1">Public Account — News Collection Tools</div>
      <div class="lead">Manage UKM profiles, upload documents, run OCR and verify MCQ answers with LLM assistance.</div>
    </div>
    <div style="text-align:right">
      {'<div class="user-pill">Signed in: ' + user + '</div>' if user else '<div class="small">Not signed in</div>'}
    </div>
  </div>

  <div class="links">
    <a class="link-btn link-primary" href="{login_page}">🔐 Login</a>
    <a class="link-btn" href="{register_page}">📝 Register</a>
    <a class="link-btn" href="{profile_page}">👤 Personal page / Dashboard</a>
    <a class="link-btn" href="/mcq_llm_good_stage">🔍 MCQ Verification</a>
    <a class="link-btn" href="/0_0_0_2_Bulk_OCR">📄 Bulk OCR</a>
  </div>

  <div class="small">
    This app stores account data locally in JSON (users.json) inside the public_account folder. Passwords are hashed with salt.
  </div>

  <div class="footer-note">
    Tip: use the sidebar (Pages) for direct access to all pages. Links above include your username in the dashboard link when you're signed in.
  </div>
</div>
"""

st.markdown(html, unsafe_allow_html=True)
import streamlit as st
from pathlib import Path
import json
from datetime import datetime
from streamlit_compat import get_query_params

ROOT = Path(__file__).parent.parent
USER_DATA_DIR = ROOT / "user_data"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

def _ensure_user():
    user = st.session_state.get("user")
    if not user:
        params = get_query_params()
        if "user" in params and params["user"]:
            st.session_state["user"] = params["user"][0]
            user = st.session_state["user"]
    return user

def load_metadata(user: str) -> list:
    mpath = USER_DATA_DIR / user / "metadata.json"
    if not mpath.exists():
        return []
    try:
        return json.loads(mpath.read_text(encoding="utf-8") or "[]")
    except Exception:
        return []

def save_metadata(user: str, meta: list):
    mpath = USER_DATA_DIR / user / "metadata.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

def save_uploaded_file(user: str, uploaded):
    files_dir = USER_DATA_DIR / user / "files" / "raw"
    files_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    fname = f"{ts}_{uploaded.name}"
    out_path = files_dir / fname
    with out_path.open("wb") as f:
        f.write(uploaded.getbuffer())
    meta = load_metadata(user)
    meta.append({
        "filename": fname,
        "original_name": uploaded.name,
        "content_type": uploaded.type,
        "size": uploaded.size,
        "uploaded_at": datetime.utcnow().isoformat() + "Z",
        "title": "",
        "description": "",
        "path": str((USER_DATA_DIR / user / 'files' / 'raw' / fname).relative_to(USER_DATA_DIR)),
    })
    save_metadata(user, meta)
    return fname

st.set_page_config(page_title="My Files", layout="centered")
st.title("📁 My Files")

user = _ensure_user()
if not user:
    st.warning("You need to be logged in to upload or view files.")
    st.markdown("- [Go to Login](/login)")
    st.stop()

st.markdown(f"**Logged in as:** `{user}`")

# Upload UI
with st.form("upload_form"):
    st.subheader("Upload files")
    title = st.text_input("Title (optional)")
    description = st.text_area("Description (optional)")
    files = st.file_uploader("Choose file(s) to upload", accept_multiple_files=True)
    submit = st.form_submit_button("Upload")
if submit and files:
    imported = 0
    meta = load_metadata(user)
    for f in files:
        saved = save_uploaded_file(user, f)
        # update the latest metadata entry with title/description
        meta = load_metadata(user)
        if meta:
            meta[-1]["title"] = title
            meta[-1]["description"] = description
        imported += 1
    save_metadata(user, meta)
    st.success(f"Uploaded {imported} file(s).")

# List existing files
st.subheader("Your uploaded files")
meta = load_metadata(user)
if not meta:
    st.info("No files uploaded yet.")
else:
    for entry in reversed(meta):
        fn = entry["filename"]
        user_file = USER_DATA_DIR / user / "files" / "raw" / fn
        col1, col2, col3 = st.columns([4, 1, 1])
        with col1:
            st.markdown(f"**{entry.get('title') or entry['original_name']}** — _{entry.get('description','')}_")
            st.caption(f"{entry['original_name']} · {entry.get('content_type','')} · {entry.get('size',0)} bytes · {entry['uploaded_at']}")
        with col2:
            if user_file.exists():
                data = user_file.read_bytes()
                st.download_button("Download", data=data, file_name=entry["original_name"], key=f"dl_{fn}")
        with col3:
            if st.button("Delete", key=f"del_{fn}"):
                try:
                    user_file.unlink()
                except Exception:
                    pass
                # remove from metadata
                m2 = [m for m in meta if m["filename"] != fn]
                save_metadata(user, m2)
                st.experimental_rerun()

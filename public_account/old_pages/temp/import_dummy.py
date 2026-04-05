import streamlit as st
from pathlib import Path
import json
import os
import hashlib
from datetime import datetime

ROOT = Path(__file__).parent.parent
DATA_FILE = ROOT / "users.json"
DUMMY_FILE = ROOT / "users_dummy.json"

def load_users():
    if not DATA_FILE.exists():
        return []
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8") or "{}")
        return raw.get("users", [])
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

def load_dummy():
    if not DUMMY_FILE.exists():
        return []
    try:
        raw = json.loads(DUMMY_FILE.read_text(encoding="utf-8") or "{}")
        return raw.get("users", [])
    except Exception:
        return []

def prepare_user_from_dummy(d):
    # Accepts legacy dummy user with plaintext "password"
    username = d.get("username")
    role = d.get("role", "UKM")
    pwd = d.get("password") or d.get("pwd") or ""
    salt_hex, hash_hex = hash_password(pwd)
    return {
        "username": username,
        "role": role,
        "salt": salt_hex,
        "password_hash": hash_hex,
        "created_at": datetime.utcnow().isoformat() + "Z"
    }

st.title("Import dummy users")
st.info("This page imports users from users_dummy.json into users.json. Plaintext passwords in dummy file will be hashed before saving.")

dummy = load_dummy()
if not dummy:
    st.warning("No dummy users found at: " + str(DUMMY_FILE))
else:
    st.subheader("Dummy users preview")
    preview = [{"username": d.get("username"), "role": d.get("role", "UKM"), "password": "(hidden)"} for d in dummy]
    st.table(preview)

col1, col2 = st.columns(2)

with col1:
    if st.button("Merge dummy users into users.json"):
        existing = load_users()
        imported = 0
        skipped = 0
        for d in dummy:
            uname = d.get("username")
            if not uname:
                continue
            if username_exists(uname, existing):
                skipped += 1
                continue
            existing.append(prepare_user_from_dummy(d))
            imported += 1
        save_users(existing)
        st.success(f"Imported {imported} users, skipped {skipped} existing users.")
with col2:
    if st.button("Overwrite users.json with dummy users"):
        new_users = []
        for d in dummy:
            uname = d.get("username")
            if not uname:
                continue
            new_users.append(prepare_user_from_dummy(d))
        save_users(new_users)
        st.success(f"Overwrote users.json with {len(new_users)} users.")

st.markdown("---")
st.subheader("Current users.json")
st.code(DATA_FILE.read_text(encoding="utf-8") if DATA_FILE.exists() else "{}")
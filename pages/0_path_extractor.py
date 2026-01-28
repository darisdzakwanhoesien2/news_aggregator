import streamlit as st
from pathlib import Path
from bs4 import BeautifulSoup
from lxml import etree
import json
import uuid
from datetime import datetime
import requests
import re
from urllib.parse import urljoin, urlparse

# =====================================
# PAGE CONFIG
# =====================================

st.set_page_config(layout="wide")
st.title("🔎 HTML / XML / JSON Path Extractor → JSON (Bulk Mode)")

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "."
HTML_DIR = DATA_DIR / "temporary_pear"
OUTPUT_FILE = DATA_DIR / "extracted_selectors.json"

HTML_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# =====================================
# URL HANDLING
# =====================================

URL_REGEX = re.compile(
    r"(https?://[^\s\"'<>]+|//[^\s\"'<>]+|www\.[^\s\"'<>]+)",
    re.IGNORECASE
)

def normalize_url(raw_url, base_url=None):
    if not raw_url:
        return None

    raw_url = raw_url.strip()

    # //cdn.site.com/file.js
    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url

    # www.site.com/page
    elif raw_url.startswith("www."):
        raw_url = "https://" + raw_url

    # /relative/path
    elif raw_url.startswith("/") and base_url:
        raw_url = urljoin(base_url, raw_url)

    parsed = urlparse(raw_url)

    if not parsed.scheme:
        return None

    # Force HTTPS
    if parsed.scheme == "http":
        raw_url = raw_url.replace("http://", "https://", 1)

    return raw_url


def extract_url_from_text(text, base_url=None):
    if not text:
        return None

    match = URL_REGEX.search(text)
    if not match:
        return None

    return normalize_url(match.group(1), base_url)


def find_parent_link(el):
    """
    Walk upward until we find an <a href=""> parent.
    """
    parent = el
    while parent is not None:
        if parent.tag == "a":
            href = parent.attrib.get("href")
            if href:
                return href
        parent = parent.getparent()
    return None

# =====================================
# HELPERS
# =====================================

def detect_type(raw: str):
    raw = raw.strip()
    if raw.startswith("{") or raw.startswith("["):
        return "json"

    low = raw.lower()
    if low.startswith("<?xml") or low.startswith("<rss") or low.startswith("<feed"):
        return "xml"

    return "html"


def fetch_url(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.text


def build_xpath(element):
    path = []
    while element is not None and element.tag:
        parent = element.getparent()
        if parent is None:
            path.append(element.tag)
            break
        index = parent.index(element) + 1
        path.append(f"{element.tag}[{index}]")
        element = parent
    return "/" + "/".join(reversed(path))


def parse_document(raw, doc_type):
    if doc_type == "html":
        soup = BeautifulSoup(raw, "html.parser")
        tree = etree.HTML(str(soup))
    else:
        tree = etree.fromstring(raw.encode())
    return tree


def extract_candidates(tree):
    elements = []
    for el in tree.iter():
        txt = (el.text or "").strip()
        if txt:
            elements.append(el)
    return elements


def flatten_json(obj, prefix=""):
    rows = []

    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            rows.extend(flatten_json(v, path))

    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            path = f"{prefix}[{i}]"
            rows.extend(flatten_json(v, path))

    else:
        rows.append((prefix, obj))

    return rows


def extract_json_records(raw_json, source_name):
    parsed = json.loads(raw_json)
    flattened = flatten_json(parsed)

    records = []
    seen = set()

    for path, value in flattened:
        if value is None:
            continue

        text = str(value).strip()
        if not text:
            continue

        detected_url = extract_url_from_text(text, source_name)

        dedup_key = (path, text)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        record = {
            "id": str(uuid.uuid4()),
            "source_file": source_name,
            "doc_type": "json",
            "json_path": path,
            "value": text,
            "url": detected_url,
            "timestamp": datetime.utcnow().isoformat()
        }

        records.append(record)

    return records


def extract_all_records(elements, source_name, doc_type):
    records = []
    seen = set()

    for el in elements:
        text = (el.text or "").strip()
        if not text:
            continue

        xpath = build_xpath(el)

        # ✅ NEW: Find parent <a href="">
        raw_url = (
            el.attrib.get("href") or
            el.attrib.get("src") or
            find_parent_link(el) or
            extract_url_from_text(text, source_name)
        )

        url = normalize_url(raw_url, source_name)

        dedup_key = (xpath, text)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        record = {
            "id": str(uuid.uuid4()),
            "source_file": source_name,
            "doc_type": doc_type,
            "tag": el.tag,
            "xpath": xpath,
            "text": text,
            "url": url,   # ✅ NOW WORKS
            "attributes": dict(el.attrib),
            "timestamp": datetime.utcnow().isoformat()
        }

        records.append(record)

    return records


def load_existing_records():
    if OUTPUT_FILE.exists():
        try:
            return json.loads(OUTPUT_FILE.read_text())
        except Exception:
            return []
    return []


def save_all_records(records):
    existing = load_existing_records()
    combined = existing + records
    OUTPUT_FILE.write_text(json.dumps(combined, indent=2))
    return len(records), len(combined)

# =====================================
# INPUT MODE
# =====================================

st.sidebar.header("📥 Input Mode")

mode = st.sidebar.radio(
    "Choose source:",
    [
        "Paste HTML",
        "Upload HTML File",
        "Select Stored HTML",
        "🌐 Load from URL"
    ]
)

raw_html = None
source_name = None

# ---------- Paste Mode ----------
if mode == "Paste HTML":
    raw_html = st.text_area("📋 Paste HTML / XML / JSON", height=280)
    source_name = "pasted_html"

# ---------- Upload Mode ----------
elif mode == "Upload HTML File":
    uploaded = st.file_uploader("📤 Upload file", type=["html", "xml", "txt", "json"])
    if uploaded:
        raw_html = uploaded.read().decode("utf-8", errors="ignore")
        source_name = uploaded.name

# ---------- Select Stored ----------
elif mode == "Select Stored HTML":
    files = sorted([f.name for f in HTML_DIR.glob("*")])
    if files:
        selected_file = st.selectbox("📂 Select stored file", files)
        path = HTML_DIR / selected_file
        raw_html = path.read_text(encoding="utf-8", errors="ignore")
        source_name = selected_file
    else:
        st.warning("No stored files found.")

# ---------- URL Mode ----------
else:
    url_input = st.text_input("🌍 Enter URL (HTML / XML / JSON)")
    if st.button("⬇️ Fetch URL") and url_input:
        try:
            raw_html = fetch_url(url_input)
            source_name = url_input
            st.success("URL fetched successfully.")
        except Exception as e:
            st.error(f"❌ Failed to fetch URL: {e}")
            st.stop()

# =====================================
# PARSE + EXTRACT
# =====================================

if not raw_html:
    st.stop()

doc_type = detect_type(raw_html)
st.info(f"Detected document type: **{doc_type.upper()}**")

# ---------- JSON ----------
if doc_type == "json":
    json_records = extract_json_records(raw_html, source_name)
    st.success(f"Found {len(json_records)} JSON values.")
    st.dataframe(json_records[:200], use_container_width=True)

# ---------- HTML / XML ----------
else:
    tree = parse_document(raw_html, doc_type)
    elements = extract_candidates(tree)
    st.success(f"Found {len(elements)} candidate elements with text.")

# =====================================
# BULK SAVE
# =====================================

st.divider()
st.subheader("🚀 Bulk Extraction")

if st.button("💾 Save ALL Extractions"):
    if doc_type == "json":
        batch = json_records
    else:
        batch = extract_all_records(elements, source_name, doc_type)

    if not batch:
        st.warning("No records found.")
        st.stop()

    saved_count, total_count = save_all_records(batch)

    st.success(f"✅ Saved {saved_count} new records")
    st.info(f"📦 Total records in JSON: {total_count}")

# =====================================
# VIEW STORED DATA
# =====================================

with st.expander("📦 View Stored JSON Records"):
    data = load_existing_records()
    st.json(data[:200])
    if len(data) > 200:
        st.caption(f"Showing first 200 of {len(data)} records")


# import streamlit as st
# from pathlib import Path
# from bs4 import BeautifulSoup
# from lxml import etree
# import json
# import uuid
# from datetime import datetime
# import requests
# import re

# # =====================================
# # PAGE CONFIG
# # =====================================

# st.set_page_config(layout="wide")
# st.title("🔎 HTML / XML / JSON Path Extractor → JSON (Bulk Mode)")

# BASE_DIR = Path(__file__).resolve().parents[1]
# DATA_DIR = BASE_DIR / "."
# HTML_DIR = DATA_DIR / "temporary_pear"
# OUTPUT_FILE = DATA_DIR / "extracted_selectors.json"

# HTML_DIR.mkdir(parents=True, exist_ok=True)
# DATA_DIR.mkdir(exist_ok=True)

# # =====================================
# # URL NORMALIZATION
# # =====================================

# URL_REGEX = re.compile(r"(https?://[^\s\"'<>]+|www\.[^\s\"'<>]+)", re.IGNORECASE)

# def normalize_url(url):
#     if not url:
#         return None

#     url = url.strip()

#     # Already HTTPS
#     if url.startswith("https://"):
#         return url

#     # Upgrade HTTP → HTTPS
#     if url.startswith("http://"):
#         return "https://" + url[len("http://"):]

#     # Missing scheme
#     if url.startswith("www."):
#         return "https://" + url

#     return None


# def extract_url_from_text(text):
#     if not text:
#         return None

#     match = URL_REGEX.search(text)
#     if not match:
#         return None

#     raw_url = match.group(1)
#     return normalize_url(raw_url)

# # =====================================
# # HELPERS
# # =====================================

# def detect_type(raw: str):
#     raw = raw.strip()
#     if raw.startswith("{") or raw.startswith("["):
#         return "json"

#     low = raw.lower()
#     if low.startswith("<?xml") or low.startswith("<rss") or low.startswith("<feed"):
#         return "xml"

#     return "html"


# def fetch_url(url):
#     headers = {"User-Agent": "Mozilla/5.0"}
#     r = requests.get(url, headers=headers, timeout=20)
#     r.raise_for_status()
#     return r.text


# def build_xpath(element):
#     path = []
#     while element is not None and element.tag:
#         parent = element.getparent()
#         if parent is None:
#             path.append(element.tag)
#             break
#         index = parent.index(element) + 1
#         path.append(f"{element.tag}[{index}]")
#         element = parent
#     return "/" + "/".join(reversed(path))


# def parse_document(raw, doc_type):
#     if doc_type == "html":
#         soup = BeautifulSoup(raw, "html.parser")
#         tree = etree.HTML(str(soup))
#     else:
#         tree = etree.fromstring(raw.encode())
#     return tree


# def extract_candidates(tree):
#     elements = []
#     for el in tree.iter():
#         txt = (el.text or "").strip()
#         if txt:
#             elements.append(el)
#     return elements


# def flatten_json(obj, prefix=""):
#     rows = []

#     if isinstance(obj, dict):
#         for k, v in obj.items():
#             path = f"{prefix}.{k}" if prefix else k
#             rows.extend(flatten_json(v, path))

#     elif isinstance(obj, list):
#         for i, v in enumerate(obj):
#             path = f"{prefix}[{i}]"
#             rows.extend(flatten_json(v, path))

#     else:
#         rows.append((prefix, obj))

#     return rows


# def extract_json_records(raw_json, source_name):
#     parsed = json.loads(raw_json)
#     flattened = flatten_json(parsed)

#     records = []
#     seen = set()

#     for path, value in flattened:
#         if value is None:
#             continue

#         text = str(value).strip()
#         if not text:
#             continue

#         detected_url = extract_url_from_text(text)

#         dedup_key = (path, text)
#         if dedup_key in seen:
#             continue
#         seen.add(dedup_key)

#         record = {
#             "id": str(uuid.uuid4()),
#             "source_file": source_name,
#             "doc_type": "json",
#             "json_path": path,
#             "value": text,
#             "url": detected_url,     # ✅ HTTPS normalized
#             "timestamp": datetime.utcnow().isoformat()
#         }

#         records.append(record)

#     return records


# def extract_all_records(elements, source_name, doc_type):
#     records = []
#     seen = set()

#     for el in elements:
#         text = (el.text or "").strip()
#         if not text:
#             continue

#         xpath = build_xpath(el)

#         raw_url = (
#             el.attrib.get("href") or
#             el.attrib.get("src") or
#             extract_url_from_text(text)
#         )

#         url = normalize_url(raw_url)

#         dedup_key = (xpath, text)
#         if dedup_key in seen:
#             continue
#         seen.add(dedup_key)

#         record = {
#             "id": str(uuid.uuid4()),
#             "source_file": source_name,
#             "doc_type": doc_type,
#             "tag": el.tag,
#             "xpath": xpath,
#             "text": text,
#             "url": url,              # ✅ HTTPS normalized
#             "attributes": dict(el.attrib),
#             "timestamp": datetime.utcnow().isoformat()
#         }

#         records.append(record)

#     return records


# def load_existing_records():
#     if OUTPUT_FILE.exists():
#         try:
#             return json.loads(OUTPUT_FILE.read_text())
#         except Exception:
#             return []
#     return []


# def save_all_records(records):
#     existing = load_existing_records()
#     combined = existing + records
#     OUTPUT_FILE.write_text(json.dumps(combined, indent=2))
#     return len(records), len(combined)

# # =====================================
# # INPUT MODE
# # =====================================

# st.sidebar.header("📥 Input Mode")

# mode = st.sidebar.radio(
#     "Choose source:",
#     [
#         "Paste HTML",
#         "Upload HTML File",
#         "Select Stored HTML",
#         "🌐 Load from URL"
#     ]
# )

# raw_html = None
# source_name = None

# # ---------- Paste Mode ----------
# if mode == "Paste HTML":
#     raw_html = st.text_area("📋 Paste HTML / XML / JSON", height=280)

#     if st.button("💾 Store Content") and raw_html.strip():
#         fname = f"pasted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
#         (HTML_DIR / fname).write_text(raw_html, encoding="utf-8")
#         st.success(f"Saved as {fname}")

#     source_name = "pasted_content"


# # ---------- Upload Mode ----------
# elif mode == "Upload HTML File":
#     uploaded = st.file_uploader("📤 Upload file", type=["html", "xml", "txt", "json"])

#     if uploaded:
#         raw_html = uploaded.read().decode("utf-8", errors="ignore")
#         source_name = uploaded.name

#         if st.button("💾 Store Uploaded File"):
#             (HTML_DIR / uploaded.name).write_text(raw_html, encoding="utf-8")
#             st.success("File saved.")


# # ---------- Select Stored ----------
# elif mode == "Select Stored HTML":
#     files = sorted([f.name for f in HTML_DIR.glob("*")])
#     if not files:
#         st.warning("No stored files found.")
#     else:
#         selected_file = st.selectbox("📂 Select stored file", files)
#         path = HTML_DIR / selected_file
#         raw_html = path.read_text(encoding="utf-8", errors="ignore")
#         source_name = selected_file

#         with st.expander("👁 Preview Content"):
#             st.code(raw_html[:5000])


# # ---------- URL Mode ----------
# else:
#     url = st.text_input("🌍 Enter URL (HTML / XML / JSON)")

#     if st.button("⬇️ Fetch URL") and url:
#         try:
#             raw_html = fetch_url(url)
#             source_name = url.replace("https://", "").replace("http://", "").replace("/", "_")

#             st.success("URL fetched successfully.")

#             with st.expander("👁 Preview Content"):
#                 st.code(raw_html[:5000])

#         except Exception as e:
#             st.error(f"❌ Failed to fetch URL: {e}")
#             st.stop()


# # =====================================
# # PARSE + EXTRACT
# # =====================================

# if not raw_html:
#     st.stop()

# doc_type = detect_type(raw_html)
# st.info(f"Detected document type: **{doc_type.upper()}**")

# # ---------- JSON ----------
# if doc_type == "json":
#     try:
#         json_records = extract_json_records(raw_html, source_name)
#         st.success(f"Found {len(json_records)} JSON values.")
#         st.dataframe(json_records[:300], use_container_width=True)
#     except Exception as e:
#         st.error(f"❌ JSON parse error: {e}")
#         st.stop()

# # ---------- HTML / XML ----------
# else:
#     try:
#         tree = parse_document(raw_html, doc_type)
#         elements = extract_candidates(tree)
#         st.success(f"Found {len(elements)} candidate elements with text.")
#     except Exception as e:
#         st.error(f"❌ Parse error: {e}")
#         st.stop()


# # =====================================
# # BULK SAVE
# # =====================================

# st.divider()
# st.subheader("🚀 Bulk Extraction")

# if st.button("💾 Save ALL Extractions"):
#     with st.spinner("Saving..."):

#         if doc_type == "json":
#             batch = json_records
#         else:
#             batch = extract_all_records(elements, source_name, doc_type)

#         if not batch:
#             st.warning("No records found.")
#             st.stop()

#         saved_count, total_count = save_all_records(batch)

#     st.success(f"✅ Saved {saved_count} new records")
#     st.info(f"📦 Total records in JSON: {total_count}")


# # =====================================
# # VIEW STORED DATA
# # =====================================

# with st.expander("📦 View Stored JSON Records"):
#     data = load_existing_records()
#     st.json(data[:200])
#     if len(data) > 200:
#         st.caption(f"Showing first 200 of {len(data)} records")


# import streamlit as st
# from pathlib import Path
# from bs4 import BeautifulSoup
# from lxml import etree
# import json
# import uuid
# from datetime import datetime
# import requests
# import re

# # =====================================
# # PAGE CONFIG
# # =====================================

# st.set_page_config(layout="wide")
# st.title("🔎 HTML / XML / JSON Path Extractor → JSON (Bulk Mode)")

# BASE_DIR = Path(__file__).resolve().parents[1]
# DATA_DIR = BASE_DIR / "."
# HTML_DIR = DATA_DIR / "temporary_pear"
# OUTPUT_FILE = DATA_DIR / "extracted_selectors.json"

# HTML_DIR.mkdir(parents=True, exist_ok=True)
# DATA_DIR.mkdir(exist_ok=True)

# # =====================================
# # URL DETECTION
# # =====================================

# URL_REGEX = re.compile(r"(https?://[^\s\"'<>]+)", re.IGNORECASE)

# def extract_url_from_text(text):
#     if not text:
#         return None
#     match = URL_REGEX.search(text)
#     if match:
#         return match.group(1)
#     return None

# # =====================================
# # HELPERS
# # =====================================

# def detect_type(raw: str):
#     raw = raw.strip()
#     if raw.startswith("{") or raw.startswith("["):
#         return "json"

#     low = raw.lower()
#     if low.startswith("<?xml") or low.startswith("<rss") or low.startswith("<feed"):
#         return "xml"

#     return "html"


# def fetch_url(url):
#     headers = {"User-Agent": "Mozilla/5.0"}
#     r = requests.get(url, headers=headers, timeout=20)
#     r.raise_for_status()
#     return r.text


# def build_xpath(element):
#     path = []
#     while element is not None and element.tag:
#         parent = element.getparent()
#         if parent is None:
#             path.append(element.tag)
#             break
#         index = parent.index(element) + 1
#         path.append(f"{element.tag}[{index}]")
#         element = parent
#     return "/" + "/".join(reversed(path))


# def parse_document(raw, doc_type):
#     if doc_type == "html":
#         soup = BeautifulSoup(raw, "html.parser")
#         tree = etree.HTML(str(soup))
#     else:
#         tree = etree.fromstring(raw.encode())
#     return tree


# def extract_candidates(tree):
#     elements = []
#     for el in tree.iter():
#         txt = (el.text or "").strip()
#         if txt:
#             elements.append(el)
#     return elements


# def flatten_json(obj, prefix=""):
#     rows = []

#     if isinstance(obj, dict):
#         for k, v in obj.items():
#             path = f"{prefix}.{k}" if prefix else k
#             rows.extend(flatten_json(v, path))

#     elif isinstance(obj, list):
#         for i, v in enumerate(obj):
#             path = f"{prefix}[{i}]"
#             rows.extend(flatten_json(v, path))

#     else:
#         rows.append((prefix, obj))

#     return rows


# def extract_json_records(raw_json, source_name):
#     parsed = json.loads(raw_json)
#     flattened = flatten_json(parsed)

#     records = []
#     seen = set()

#     for path, value in flattened:
#         if value is None:
#             continue

#         text = str(value).strip()
#         if not text:
#             continue

#         detected_url = extract_url_from_text(text)

#         dedup_key = (path, text)
#         if dedup_key in seen:
#             continue
#         seen.add(dedup_key)

#         record = {
#             "id": str(uuid.uuid4()),
#             "source_file": source_name,
#             "doc_type": "json",
#             "json_path": path,
#             "value": text,
#             "url": detected_url,  # ✅ URL extracted
#             "timestamp": datetime.utcnow().isoformat()
#         }

#         records.append(record)

#     return records


# def extract_all_records(elements, source_name, doc_type):
#     records = []
#     seen = set()

#     for el in elements:
#         text = (el.text or "").strip()
#         if not text:
#             continue

#         xpath = build_xpath(el)
#         url = el.attrib.get("href") or el.attrib.get("src") or extract_url_from_text(text)

#         dedup_key = (xpath, text)
#         if dedup_key in seen:
#             continue
#         seen.add(dedup_key)

#         record = {
#             "id": str(uuid.uuid4()),
#             "source_file": source_name,
#             "doc_type": doc_type,
#             "tag": el.tag,
#             "xpath": xpath,
#             "text": text,
#             "url": url,  # ✅ URL extracted
#             "attributes": dict(el.attrib),
#             "timestamp": datetime.utcnow().isoformat()
#         }

#         records.append(record)

#     return records


# def load_existing_records():
#     if OUTPUT_FILE.exists():
#         try:
#             return json.loads(OUTPUT_FILE.read_text())
#         except Exception:
#             return []
#     return []


# def save_all_records(records):
#     existing = load_existing_records()
#     combined = existing + records
#     OUTPUT_FILE.write_text(json.dumps(combined, indent=2))
#     return len(records), len(combined)

# # =====================================
# # INPUT MODE
# # =====================================

# st.sidebar.header("📥 Input Mode")

# mode = st.sidebar.radio(
#     "Choose source:",
#     [
#         "Paste HTML",
#         "Upload HTML File",
#         "Select Stored HTML",
#         "🌐 Load from URL"
#     ]
# )

# raw_html = None
# source_name = None

# # ---------- Paste Mode ----------
# if mode == "Paste HTML":
#     raw_html = st.text_area("📋 Paste HTML / XML / JSON", height=280)

#     if st.button("💾 Store Content") and raw_html.strip():
#         fname = f"pasted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
#         (HTML_DIR / fname).write_text(raw_html, encoding="utf-8")
#         st.success(f"Saved as {fname}")

#     source_name = "pasted_content"


# # ---------- Upload Mode ----------
# elif mode == "Upload HTML File":
#     uploaded = st.file_uploader("📤 Upload file", type=["html", "xml", "txt", "json"])

#     if uploaded:
#         raw_html = uploaded.read().decode("utf-8", errors="ignore")
#         source_name = uploaded.name

#         if st.button("💾 Store Uploaded File"):
#             (HTML_DIR / uploaded.name).write_text(raw_html, encoding="utf-8")
#             st.success("File saved.")


# # ---------- Select Stored ----------
# elif mode == "Select Stored HTML":
#     files = sorted([f.name for f in HTML_DIR.glob("*")])
#     if not files:
#         st.warning("No stored files found.")
#     else:
#         selected_file = st.selectbox("📂 Select stored file", files)
#         path = HTML_DIR / selected_file
#         raw_html = path.read_text(encoding="utf-8", errors="ignore")
#         source_name = selected_file

#         with st.expander("👁 Preview Content"):
#             st.code(raw_html[:5000])


# # ---------- URL Mode ----------
# else:
#     url = st.text_input("🌍 Enter URL (HTML / XML / JSON)")

#     if st.button("⬇️ Fetch URL") and url:
#         try:
#             raw_html = fetch_url(url)
#             source_name = url.replace("https://", "").replace("http://", "").replace("/", "_")

#             st.success("URL fetched successfully.")

#             with st.expander("👁 Preview Content"):
#                 st.code(raw_html[:5000])

#         except Exception as e:
#             st.error(f"❌ Failed to fetch URL: {e}")
#             st.stop()


# # =====================================
# # PARSE + EXTRACT
# # =====================================

# if not raw_html:
#     st.stop()

# doc_type = detect_type(raw_html)
# st.info(f"Detected document type: **{doc_type.upper()}**")

# # ---------- JSON ----------
# if doc_type == "json":
#     try:
#         json_records = extract_json_records(raw_html, source_name)
#         st.success(f"Found {len(json_records)} JSON values.")
#         st.dataframe(json_records[:300], use_container_width=True)
#     except Exception as e:
#         st.error(f"❌ JSON parse error: {e}")
#         st.stop()

# # ---------- HTML / XML ----------
# else:
#     try:
#         tree = parse_document(raw_html, doc_type)
#         elements = extract_candidates(tree)
#         st.success(f"Found {len(elements)} candidate elements with text.")
#     except Exception as e:
#         st.error(f"❌ Parse error: {e}")
#         st.stop()


# # =====================================
# # BULK SAVE
# # =====================================

# st.divider()
# st.subheader("🚀 Bulk Extraction")

# if st.button("💾 Save ALL Extractions"):
#     with st.spinner("Saving..."):

#         if doc_type == "json":
#             batch = json_records
#         else:
#             batch = extract_all_records(elements, source_name, doc_type)

#         if not batch:
#             st.warning("No records found.")
#             st.stop()

#         saved_count, total_count = save_all_records(batch)

#     st.success(f"✅ Saved {saved_count} new records")
#     st.info(f"📦 Total records in JSON: {total_count}")


# # =====================================
# # VIEW STORED DATA
# # =====================================

# with st.expander("📦 View Stored JSON Records"):
#     data = load_existing_records()
#     st.json(data[:200])
#     if len(data) > 200:
#         st.caption(f"Showing first 200 of {len(data)} records")


# import streamlit as st
# from pathlib import Path
# from bs4 import BeautifulSoup
# from lxml import etree
# import json
# import uuid
# from datetime import datetime
# import requests

# # =====================================
# # PAGE CONFIG
# # =====================================

# st.set_page_config(layout="wide")
# st.title("🔎 HTML / XML / JSON Path Extractor → JSON (Bulk Mode)")

# BASE_DIR = Path(__file__).resolve().parents[1]
# DATA_DIR = BASE_DIR / "."
# HTML_DIR = DATA_DIR / "temporary_pear"
# OUTPUT_FILE = DATA_DIR / "extracted_selectors.json"

# HTML_DIR.mkdir(parents=True, exist_ok=True)
# DATA_DIR.mkdir(exist_ok=True)

# # =====================================
# # HELPERS
# # =====================================

# def detect_type(raw: str):
#     raw = raw.strip()
#     if raw.startswith("{") or raw.startswith("["):
#         return "json"

#     low = raw.lower()
#     if low.startswith("<?xml") or low.startswith("<rss") or low.startswith("<feed"):
#         return "xml"

#     return "html"


# def fetch_url(url):
#     headers = {"User-Agent": "Mozilla/5.0"}
#     r = requests.get(url, headers=headers, timeout=20)
#     r.raise_for_status()
#     return r.text


# def build_xpath(element):
#     path = []
#     while element is not None and element.tag:
#         parent = element.getparent()
#         if parent is None:
#             path.append(element.tag)
#             break
#         index = parent.index(element) + 1
#         path.append(f"{element.tag}[{index}]")
#         element = parent
#     return "/" + "/".join(reversed(path))


# def parse_document(raw, doc_type):
#     if doc_type == "html":
#         soup = BeautifulSoup(raw, "html.parser")
#         tree = etree.HTML(str(soup))
#     else:
#         tree = etree.fromstring(raw.encode())
#     return tree


# def extract_candidates(tree):
#     elements = []
#     for el in tree.iter():
#         txt = (el.text or "").strip()
#         if txt:
#             elements.append(el)
#     return elements


# def flatten_json(obj, prefix=""):
#     rows = []

#     if isinstance(obj, dict):
#         for k, v in obj.items():
#             path = f"{prefix}.{k}" if prefix else k
#             rows.extend(flatten_json(v, path))

#     elif isinstance(obj, list):
#         for i, v in enumerate(obj):
#             path = f"{prefix}[{i}]"
#             rows.extend(flatten_json(v, path))

#     else:
#         rows.append((prefix, obj))

#     return rows


# def extract_json_records(raw_json, source_name):
#     parsed = json.loads(raw_json)
#     flattened = flatten_json(parsed)

#     records = []
#     seen = set()

#     for path, value in flattened:
#         if value is None:
#             continue

#         text = str(value).strip()
#         if not text:
#             continue

#         dedup_key = (path, text)
#         if dedup_key in seen:
#             continue
#         seen.add(dedup_key)

#         record = {
#             "id": str(uuid.uuid4()),
#             "source_file": source_name,
#             "doc_type": "json",
#             "json_path": path,
#             "value": text,
#             "timestamp": datetime.utcnow().isoformat()
#         }

#         records.append(record)

#     return records


# def extract_all_records(elements, source_name, doc_type):
#     records = []
#     seen = set()

#     for el in elements:
#         text = (el.text or "").strip()
#         if not text:
#             continue

#         xpath = build_xpath(el)
#         url = el.attrib.get("href") or el.attrib.get("src")

#         dedup_key = (xpath, text)
#         if dedup_key in seen:
#             continue
#         seen.add(dedup_key)

#         record = {
#             "id": str(uuid.uuid4()),
#             "source_file": source_name,
#             "doc_type": doc_type,
#             "tag": el.tag,
#             "xpath": xpath,
#             "text": text,
#             "url": url,
#             "attributes": dict(el.attrib),
#             "timestamp": datetime.utcnow().isoformat()
#         }

#         records.append(record)

#     return records


# def load_existing_records():
#     if OUTPUT_FILE.exists():
#         try:
#             return json.loads(OUTPUT_FILE.read_text())
#         except Exception:
#             return []
#     return []


# def save_all_records(records):
#     existing = load_existing_records()
#     combined = existing + records
#     OUTPUT_FILE.write_text(json.dumps(combined, indent=2))
#     return len(records), len(combined)

# # =====================================
# # INPUT MODE
# # =====================================

# st.sidebar.header("📥 Input Mode")

# mode = st.sidebar.radio(
#     "Choose source:",
#     [
#         "Paste HTML",
#         "Upload HTML File",
#         "Select Stored HTML",
#         "🌐 Load from URL"
#     ]
# )

# raw_html = None
# source_name = None

# # ---------- Paste Mode ----------
# if mode == "Paste HTML":
#     raw_html = st.text_area("📋 Paste HTML / XML / JSON", height=280)

#     if st.button("💾 Store HTML") and raw_html.strip():
#         fname = f"pasted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
#         (HTML_DIR / fname).write_text(raw_html, encoding="utf-8")
#         st.success(f"Saved as {fname}")

#     source_name = "pasted_content"


# # ---------- Upload Mode ----------
# elif mode == "Upload HTML File":
#     uploaded = st.file_uploader("📤 Upload file", type=["html", "xml", "txt", "json"])

#     if uploaded:
#         raw_html = uploaded.read().decode("utf-8", errors="ignore")
#         source_name = uploaded.name

#         if st.button("💾 Store Uploaded File"):
#             (HTML_DIR / uploaded.name).write_text(raw_html, encoding="utf-8")
#             st.success("File saved.")


# # ---------- Select Stored ----------
# elif mode == "Select Stored HTML":
#     files = sorted([f.name for f in HTML_DIR.glob("*")])
#     if not files:
#         st.warning("No stored files found.")
#     else:
#         selected_file = st.selectbox("📂 Select stored file", files)
#         path = HTML_DIR / selected_file
#         raw_html = path.read_text(encoding="utf-8", errors="ignore")
#         source_name = selected_file

#         with st.expander("👁 Preview Content"):
#             st.code(raw_html[:5000])


# # ---------- URL Mode ----------
# else:
#     url = st.text_input("🌍 Enter URL (HTML / XML / JSON)")

#     if st.button("⬇️ Fetch URL") and url:
#         try:
#             raw_html = fetch_url(url)
#             source_name = url.replace("https://", "").replace("http://", "").replace("/", "_")

#             st.success("URL fetched successfully.")

#             with st.expander("👁 Preview Content"):
#                 st.code(raw_html[:5000])

#         except Exception as e:
#             st.error(f"❌ Failed to fetch URL: {e}")
#             st.stop()


# # =====================================
# # PARSE + EXTRACT
# # =====================================

# if not raw_html:
#     st.stop()

# doc_type = detect_type(raw_html)
# st.info(f"Detected document type: **{doc_type.upper()}**")

# # ---------- JSON ----------
# if doc_type == "json":
#     try:
#         json_records = extract_json_records(raw_html, source_name)
#         st.success(f"Found {len(json_records)} JSON values.")
#         st.dataframe(json_records[:300], use_container_width=True)
#     except Exception as e:
#         st.error(f"❌ JSON parse error: {e}")
#         st.stop()

# # ---------- HTML / XML ----------
# else:
#     try:
#         tree = parse_document(raw_html, doc_type)
#         elements = extract_candidates(tree)
#         st.success(f"Found {len(elements)} candidate elements with text.")
#     except Exception as e:
#         st.error(f"❌ Parse error: {e}")
#         st.stop()


# # =====================================
# # BULK SAVE
# # =====================================

# st.divider()
# st.subheader("🚀 Bulk Extraction")

# if st.button("💾 Save ALL Extractions"):
#     with st.spinner("Saving..."):

#         if doc_type == "json":
#             batch = json_records
#         else:
#             batch = extract_all_records(elements, source_name, doc_type)

#         if not batch:
#             st.warning("No records found.")
#             st.stop()

#         saved_count, total_count = save_all_records(batch)

#     st.success(f"✅ Saved {saved_count} new records")
#     st.info(f"📦 Total records in JSON: {total_count}")


# # =====================================
# # VIEW STORED DATA
# # =====================================

# with st.expander("📦 View Stored JSON Records"):
#     data = load_existing_records()
#     st.json(data[:200])
#     if len(data) > 200:
#         st.caption(f"Showing first 200 of {len(data)} records")


# import streamlit as st
# from pathlib import Path
# from bs4 import BeautifulSoup
# from lxml import etree
# import json
# import uuid
# from datetime import datetime

# # =====================================
# # PAGE CONFIG
# # =====================================

# st.set_page_config(layout="wide")
# st.title("🔎 HTML / XML Path Extractor → JSON (Bulk Mode)")

# BASE_DIR = Path(__file__).resolve().parents[1]
# DATA_DIR = BASE_DIR / "."
# HTML_DIR = DATA_DIR / "temporary_pear"
# OUTPUT_FILE = DATA_DIR / "extracted_selectors.json"

# HTML_DIR.mkdir(parents=True, exist_ok=True)
# DATA_DIR.mkdir(exist_ok=True)

# # =====================================
# # HELPERS
# # =====================================

# def detect_type(raw: str):
#     raw = raw.strip().lower()
#     if raw.startswith("<?xml") or raw.startswith("<rss") or raw.startswith("<feed"):
#         return "xml"
#     return "html"


# def build_xpath(element):
#     path = []
#     while element is not None and element.tag:
#         parent = element.getparent()
#         if parent is None:
#             path.append(element.tag)
#             break
#         index = parent.index(element) + 1
#         path.append(f"{element.tag}[{index}]")
#         element = parent
#     return "/" + "/".join(reversed(path))


# def parse_document(raw, doc_type):
#     if doc_type == "html":
#         soup = BeautifulSoup(raw, "html.parser")
#         tree = etree.HTML(str(soup))
#     else:
#         tree = etree.fromstring(raw.encode())
#     return tree


# def extract_candidates(tree):
#     elements = []
#     for el in tree.iter():
#         txt = (el.text or "").strip()
#         if txt:
#             elements.append(el)
#     return elements


# def save_html_file(name: str, content: str):
#     path = HTML_DIR / name
#     path.write_text(content, encoding="utf-8")
#     return path


# def load_existing_records():
#     if OUTPUT_FILE.exists():
#         try:
#             return json.loads(OUTPUT_FILE.read_text())
#         except Exception:
#             return []
#     return []


# def save_all_records(records):
#     existing = load_existing_records()
#     combined = existing + records
#     OUTPUT_FILE.write_text(json.dumps(combined, indent=2))
#     return len(records), len(combined)


# def extract_all_records(elements, source_name, doc_type):
#     records = []
#     seen = set()

#     for el in elements:
#         text = (el.text or "").strip()
#         if not text:
#             continue

#         xpath = build_xpath(el)
#         url = el.attrib.get("href") or el.attrib.get("src")

#         dedup_key = (xpath, text)
#         if dedup_key in seen:
#             continue
#         seen.add(dedup_key)

#         record = {
#             "id": str(uuid.uuid4()),
#             "source_file": source_name,
#             "doc_type": doc_type,
#             "tag": el.tag,
#             "xpath": xpath,
#             "text": text,
#             "url": url,
#             "attributes": dict(el.attrib),
#             "timestamp": datetime.utcnow().isoformat()
#         }

#         records.append(record)

#     return records


# # =====================================
# # INPUT MODE
# # =====================================

# st.sidebar.header("📥 Input Mode")

# mode = st.sidebar.radio(
#     "Choose HTML source:",
#     ["Paste HTML", "Upload HTML File", "Select Stored HTML"]
# )

# raw_html = None
# source_name = None

# # ---------- Paste Mode ----------
# if mode == "Paste HTML":
#     raw_html = st.text_area(
#         "📋 Paste HTML or XML",
#         height=280,
#         placeholder="<html>...</html>"
#     )

#     if st.button("💾 Store HTML") and raw_html.strip():
#         fname = f"pasted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
#         save_html_file(fname, raw_html)
#         st.success(f"Saved as {fname}")

#     source_name = "pasted_html"


# # ---------- Upload Mode ----------
# elif mode == "Upload HTML File":
#     uploaded = st.file_uploader("📤 Upload HTML file", type=["html", "xml", "txt"])

#     if uploaded:
#         raw_html = uploaded.read().decode("utf-8", errors="ignore")
#         source_name = uploaded.name

#         if st.button("💾 Store Uploaded File"):
#             save_html_file(uploaded.name, raw_html)
#             st.success("File saved.")


# # ---------- Select Stored ----------
# else:
#     files = sorted([f.name for f in HTML_DIR.glob("*")])
#     if not files:
#         st.warning("No stored HTML files found.")
#     else:
#         selected_file = st.selectbox("📂 Select stored HTML", files)
#         path = HTML_DIR / selected_file
#         raw_html = path.read_text(encoding="utf-8", errors="ignore")
#         source_name = selected_file

#         with st.expander("👁 Preview HTML"):
#             st.code(raw_html[:5000])


# # =====================================
# # PARSE + EXTRACT
# # =====================================

# if not raw_html or not raw_html.strip():
#     st.stop()

# doc_type = detect_type(raw_html)
# st.info(f"Detected document type: **{doc_type.upper()}**")

# try:
#     tree = parse_document(raw_html, doc_type)
# except Exception as e:
#     st.error(f"❌ Parse error: {e}")
#     st.stop()

# elements = extract_candidates(tree)
# st.success(f"Found {len(elements)} candidate elements with text.")


# # =====================================
# # ELEMENT PREVIEW (OPTIONAL)
# # =====================================

# st.subheader("🔍 Element Preview")

# MAX_SHOW = 300
# labels = []

# for idx, el in enumerate(elements[:MAX_SHOW]):
#     preview = (el.text or "").strip().replace("\n", " ")[:80]
#     labels.append(f"{idx}: <{el.tag}> → {preview}")

# selected = st.selectbox("Preview element", labels)

# idx = int(selected.split(":")[0])
# el = elements[idx]

# xpath = build_xpath(el)
# text = (el.text or "").strip()
# url = el.attrib.get("href") or el.attrib.get("src")

# col1, col2 = st.columns(2)

# with col1:
#     st.markdown("**XPath**")
#     st.code(xpath)
#     st.markdown("**Text**")
#     st.text_area("", text, height=120)

# with col2:
#     st.markdown("**Attributes**")
#     st.json(dict(el.attrib) if el.attrib else {})
#     st.markdown("**Detected URL**")
#     st.code(url or "—")


# # =====================================
# # BULK EXTRACTION
# # =====================================

# st.divider()
# st.subheader("🚀 Bulk Extraction")

# if st.button("💾 Save ALL Extractions"):
#     with st.spinner("Extracting all elements..."):
#         batch = extract_all_records(elements, source_name, doc_type)

#         if not batch:
#             st.warning("No valid elements found.")
#             st.stop()

#         saved_count, total_count = save_all_records(batch)

#     st.success(f"✅ Saved {saved_count} new records")
#     st.info(f"📦 Total records in JSON: {total_count}")


# # =====================================
# # VIEW STORED EXTRACTIONS
# # =====================================

# with st.expander("📦 View Stored JSON Records"):
#     data = load_existing_records()
#     st.json(data[:200])
#     if len(data) > 200:
#         st.caption(f"Showing first 200 of {len(data)} records")


# import streamlit as st
# from pathlib import Path
# from bs4 import BeautifulSoup
# from lxml import etree
# import json
# import uuid
# from datetime import datetime

# # =====================================
# # PAGE CONFIG
# # =====================================

# st.set_page_config(layout="wide")
# st.title("🔎 HTML / XML Path Extractor → JSON")

# BASE_DIR = Path(__file__).resolve().parents[1]
# DATA_DIR = BASE_DIR / "." # "data"
# HTML_DIR = DATA_DIR / "temporary_pear" # "html_inputs"
# OUTPUT_FILE = DATA_DIR / "extracted_selectors.json"

# HTML_DIR.mkdir(parents=True, exist_ok=True)
# DATA_DIR.mkdir(exist_ok=True)


# # =====================================
# # HELPERS
# # =====================================

# def detect_type(raw: str):
#     raw = raw.strip().lower()
#     if raw.startswith("<?xml") or raw.startswith("<rss") or raw.startswith("<feed"):
#         return "xml"
#     return "html"


# def build_xpath(element):
#     path = []
#     while element is not None and element.tag:
#         parent = element.getparent()
#         if parent is None:
#             path.append(element.tag)
#             break
#         index = parent.index(element) + 1
#         path.append(f"{element.tag}[{index}]")
#         element = parent
#     return "/" + "/".join(reversed(path))


# def parse_document(raw, doc_type):
#     if doc_type == "html":
#         soup = BeautifulSoup(raw, "html.parser")
#         tree = etree.HTML(str(soup))
#     else:
#         tree = etree.fromstring(raw.encode())
#     return tree


# def extract_candidates(tree):
#     elements = []
#     for el in tree.iter():
#         txt = (el.text or "").strip()
#         if txt:
#             elements.append(el)
#     return elements


# def save_html_file(name: str, content: str):
#     path = HTML_DIR / name
#     path.write_text(content, encoding="utf-8")
#     return path


# def load_existing_records():
#     if OUTPUT_FILE.exists():
#         return json.loads(OUTPUT_FILE.read_text())
#     return []


# def save_record(record):
#     data = load_existing_records()
#     data.append(record)
#     OUTPUT_FILE.write_text(json.dumps(data, indent=2))


# # =====================================
# # INPUT MODE
# # =====================================

# st.sidebar.header("📥 Input Mode")

# mode = st.sidebar.radio(
#     "Choose HTML source:",
#     ["Paste HTML", "Upload HTML File", "Select Stored HTML"]
# )

# raw_html = None
# source_name = None


# # ---------- Paste Mode ----------
# if mode == "Paste HTML":
#     raw_html = st.text_area(
#         "📋 Paste HTML or XML",
#         height=280,
#         placeholder="<html>...</html>"
#     )

#     col1, col2 = st.columns([1, 3])
#     with col1:
#         if st.button("💾 Store HTML") and raw_html.strip():
#             fname = f"pasted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
#             save_html_file(fname, raw_html)
#             st.success(f"Saved as {fname}")

#     source_name = "pasted_html"


# # ---------- Upload Mode ----------
# elif mode == "Upload HTML File":
#     uploaded = st.file_uploader("📤 Upload HTML file", type=["html", "xml", "txt"])

#     if uploaded:
#         raw_html = uploaded.read().decode("utf-8", errors="ignore")
#         source_name = uploaded.name

#         if st.button("💾 Store Uploaded File"):
#             save_html_file(uploaded.name, raw_html)
#             st.success("File saved.")


# # ---------- Select Stored ----------
# else:
#     files = sorted([f.name for f in HTML_DIR.glob("*")])
#     if not files:
#         st.warning("No stored HTML files found.")
#     else:
#         selected_file = st.selectbox("📂 Select stored HTML", files)
#         path = HTML_DIR / selected_file
#         raw_html = path.read_text(encoding="utf-8", errors="ignore")
#         source_name = selected_file

#         with st.expander("👁 Preview HTML"):
#             st.code(raw_html[:5000])


# # =====================================
# # PARSE + EXTRACT
# # =====================================

# if not raw_html or not raw_html.strip():
#     st.stop()

# doc_type = detect_type(raw_html)
# st.info(f"Detected document type: **{doc_type.upper()}**")

# try:
#     tree = parse_document(raw_html, doc_type)
# except Exception as e:
#     st.error(f"❌ Parse error: {e}")
#     st.stop()

# elements = extract_candidates(tree)
# st.success(f"Found {len(elements)} candidate elements with text.")


# # =====================================
# # ELEMENT SELECTION
# # =====================================

# labels = []
# MAX_SHOW = 300

# for idx, el in enumerate(elements[:MAX_SHOW]):
#     preview = (el.text or "").strip().replace("\n", " ")[:80]
#     labels.append(f"{idx}: <{el.tag}> → {preview}")

# selected = st.selectbox("🎯 Select element", labels)

# idx = int(selected.split(":")[0])
# el = elements[idx]

# xpath = build_xpath(el)
# text = (el.text or "").strip()
# url = el.attrib.get("href") or el.attrib.get("src")


# # =====================================
# # DISPLAY
# # =====================================

# st.subheader("📍 Extracted Info")

# col1, col2 = st.columns(2)

# with col1:
#     st.markdown("**XPath**")
#     st.code(xpath)
#     st.markdown("**Text**")
#     st.text_area("", text, height=120)

# with col2:
#     st.markdown("**Attributes**")
#     st.json(dict(el.attrib) if el.attrib else {})
#     st.markdown("**Detected URL**")
#     st.code(url or "—")


# # =====================================
# # SAVE JSON
# # =====================================

# if st.button("💾 Save Extraction to JSON"):
#     record = {
#         "id": str(uuid.uuid4()),
#         "source_file": source_name,
#         "doc_type": doc_type,
#         "tag": el.tag,
#         "xpath": xpath,
#         "text": text,
#         "url": url,
#         "attributes": dict(el.attrib),
#         "timestamp": datetime.utcnow().isoformat()
#     }

#     save_record(record)

#     st.success(f"Saved to {OUTPUT_FILE}")


# # =====================================
# # VIEW STORED EXTRACTIONS
# # =====================================

# with st.expander("📦 View Stored JSON Records"):
#     data = load_existing_records()
#     st.json(data)


# import streamlit as st
# from bs4 import BeautifulSoup
# from lxml import etree
# from pathlib import Path
# import json
# import uuid

# # ================================
# # PAGE CONFIG
# # ================================

# st.set_page_config(layout="wide")
# st.title("🔎 HTML / XML Path Extractor → JSON")

# DATA_DIR = Path("data")
# DATA_DIR.mkdir(exist_ok=True)
# OUTPUT_FILE = DATA_DIR / "selectors.json"


# # ================================
# # HELPERS
# # ================================

# def detect_type(raw):
#     raw = raw.strip().lower()
#     if raw.startswith("<?xml") or raw.startswith("<rss") or raw.startswith("<feed"):
#         return "xml"
#     return "html"


# def build_xpath(element):
#     path = []
#     while element is not None and element.tag:
#         parent = element.getparent()
#         if parent is None:
#             path.append(element.tag)
#             break
#         index = parent.index(element) + 1
#         path.append(f"{element.tag}[{index}]")
#         element = parent
#     return "/" + "/".join(reversed(path))


# def extract_candidates(tree):
#     candidates = []
#     for el in tree.iter():
#         text = (el.text or "").strip()
#         if text:
#             candidates.append(el)
#     return candidates


# # ================================
# # UI
# # ================================

# raw_html = st.text_area(
#     "📥 Paste HTML or XML here",
#     height=300,
#     placeholder="<html>...</html>"
# )

# if not raw_html.strip():
#     st.stop()

# doc_type = detect_type(raw_html)
# st.info(f"Detected document type: **{doc_type.upper()}**")

# # ================================
# # PARSE
# # ================================

# try:
#     if doc_type == "html":
#         soup = BeautifulSoup(raw_html, "html.parser")
#         tree = etree.HTML(str(soup))
#     else:
#         tree = etree.fromstring(raw_html.encode())

# except Exception as e:
#     st.error(f"❌ Parse error: {e}")
#     st.stop()

# elements = extract_candidates(tree)
# st.success(f"Found {len(elements)} candidate elements with text.")


# # ================================
# # ELEMENT SELECTION
# # ================================

# labels = []
# for idx, el in enumerate(elements[:300]):
#     preview = (el.text or "").strip()[:80]
#     labels.append(f"{idx}: <{el.tag}> → {preview}")

# selected = st.selectbox("🎯 Select element", labels)

# idx = int(selected.split(":")[0])
# el = elements[idx]

# xpath = build_xpath(el)
# text = (el.text or "").strip()
# href = el.attrib.get("href") or el.attrib.get("src")

# st.subheader("📍 Extracted Info")

# col1, col2 = st.columns(2)

# with col1:
#     st.code(xpath, language="text")
#     st.text_area("Text", text, height=100)

# with col2:
#     st.write("Attributes:")
#     st.json(el.attrib if el.attrib else {})
#     st.write("Detected URL:")
#     st.code(href or "—")


# # ================================
# # SAVE TO JSON
# # ================================

# if st.button("💾 Save to JSON"):
#     record = {
#         "id": str(uuid.uuid4()),
#         "doc_type": doc_type,
#         "xpath": xpath,
#         "tag": el.tag,
#         "text_sample": text,
#         "url": href,
#         "attributes": dict(el.attrib)
#     }

#     existing = []
#     if OUTPUT_FILE.exists():
#         existing = json.loads(OUTPUT_FILE.read_text())

#     existing.append(record)
#     OUTPUT_FILE.write_text(json.dumps(existing, indent=2))

#     st.success(f"Saved to {OUTPUT_FILE}")

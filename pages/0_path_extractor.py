import streamlit as st
from pathlib import Path
from bs4 import BeautifulSoup
from lxml import etree
import json
import uuid
from datetime import datetime

# =====================================
# PAGE CONFIG
# =====================================

st.set_page_config(layout="wide")
st.title("🔎 HTML / XML Path Extractor → JSON (Bulk Mode)")

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "."
HTML_DIR = DATA_DIR / "temporary_pear"
OUTPUT_FILE = DATA_DIR / "extracted_selectors.json"

HTML_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# =====================================
# HELPERS
# =====================================

def detect_type(raw: str):
    raw = raw.strip().lower()
    if raw.startswith("<?xml") or raw.startswith("<rss") or raw.startswith("<feed"):
        return "xml"
    return "html"


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


def save_html_file(name: str, content: str):
    path = HTML_DIR / name
    path.write_text(content, encoding="utf-8")
    return path


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


def extract_all_records(elements, source_name, doc_type):
    records = []
    seen = set()

    for el in elements:
        text = (el.text or "").strip()
        if not text:
            continue

        xpath = build_xpath(el)
        url = el.attrib.get("href") or el.attrib.get("src")

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
            "url": url,
            "attributes": dict(el.attrib),
            "timestamp": datetime.utcnow().isoformat()
        }

        records.append(record)

    return records


# =====================================
# INPUT MODE
# =====================================

st.sidebar.header("📥 Input Mode")

mode = st.sidebar.radio(
    "Choose HTML source:",
    ["Paste HTML", "Upload HTML File", "Select Stored HTML"]
)

raw_html = None
source_name = None

# ---------- Paste Mode ----------
if mode == "Paste HTML":
    raw_html = st.text_area(
        "📋 Paste HTML or XML",
        height=280,
        placeholder="<html>...</html>"
    )

    if st.button("💾 Store HTML") and raw_html.strip():
        fname = f"pasted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        save_html_file(fname, raw_html)
        st.success(f"Saved as {fname}")

    source_name = "pasted_html"


# ---------- Upload Mode ----------
elif mode == "Upload HTML File":
    uploaded = st.file_uploader("📤 Upload HTML file", type=["html", "xml", "txt"])

    if uploaded:
        raw_html = uploaded.read().decode("utf-8", errors="ignore")
        source_name = uploaded.name

        if st.button("💾 Store Uploaded File"):
            save_html_file(uploaded.name, raw_html)
            st.success("File saved.")


# ---------- Select Stored ----------
else:
    files = sorted([f.name for f in HTML_DIR.glob("*")])
    if not files:
        st.warning("No stored HTML files found.")
    else:
        selected_file = st.selectbox("📂 Select stored HTML", files)
        path = HTML_DIR / selected_file
        raw_html = path.read_text(encoding="utf-8", errors="ignore")
        source_name = selected_file

        with st.expander("👁 Preview HTML"):
            st.code(raw_html[:5000])


# =====================================
# PARSE + EXTRACT
# =====================================

if not raw_html or not raw_html.strip():
    st.stop()

doc_type = detect_type(raw_html)
st.info(f"Detected document type: **{doc_type.upper()}**")

try:
    tree = parse_document(raw_html, doc_type)
except Exception as e:
    st.error(f"❌ Parse error: {e}")
    st.stop()

elements = extract_candidates(tree)
st.success(f"Found {len(elements)} candidate elements with text.")


# =====================================
# ELEMENT PREVIEW (OPTIONAL)
# =====================================

st.subheader("🔍 Element Preview")

MAX_SHOW = 300
labels = []

for idx, el in enumerate(elements[:MAX_SHOW]):
    preview = (el.text or "").strip().replace("\n", " ")[:80]
    labels.append(f"{idx}: <{el.tag}> → {preview}")

selected = st.selectbox("Preview element", labels)

idx = int(selected.split(":")[0])
el = elements[idx]

xpath = build_xpath(el)
text = (el.text or "").strip()
url = el.attrib.get("href") or el.attrib.get("src")

col1, col2 = st.columns(2)

with col1:
    st.markdown("**XPath**")
    st.code(xpath)
    st.markdown("**Text**")
    st.text_area("", text, height=120)

with col2:
    st.markdown("**Attributes**")
    st.json(dict(el.attrib) if el.attrib else {})
    st.markdown("**Detected URL**")
    st.code(url or "—")


# =====================================
# BULK EXTRACTION
# =====================================

st.divider()
st.subheader("🚀 Bulk Extraction")

if st.button("💾 Save ALL Extractions"):
    with st.spinner("Extracting all elements..."):
        batch = extract_all_records(elements, source_name, doc_type)

        if not batch:
            st.warning("No valid elements found.")
            st.stop()

        saved_count, total_count = save_all_records(batch)

    st.success(f"✅ Saved {saved_count} new records")
    st.info(f"📦 Total records in JSON: {total_count}")


# =====================================
# VIEW STORED EXTRACTIONS
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

import streamlit as st
from extractor.storage import load_json, save_json
from extractor.pipeline import process_article
import os
import time
from _page_descriptions import render_page_description

DATA_PATH = "data/news_dataset_new.json"
EXTRACTED_PATH = "data/news_extracted.json"
LOG_PATH = "data/logs.json"

st.set_page_config(page_title="Batch Extractor", layout="wide")
st.title("📰 Batch Extractor")
render_page_description(__file__)

news_data = load_json(DATA_PATH, [])
extracted_data = load_json(EXTRACTED_PATH, [])
logs = load_json(LOG_PATH, [])

extracted_ids = {item["id"] for item in extracted_data}

st.write("Total:", len(news_data))
st.write("Extracted:", len(extracted_ids))

batch_size = st.number_input("Batch Size", 1, 100, 5)

if st.button("Start Extraction"):

    remaining = [
        article for article in news_data
        if process_article.__globals__['generate_id'](article) not in extracted_ids
    ]

    total = min(batch_size, len(remaining))
    progress = st.progress(0)

    for i in range(total):

        structured, status = process_article(
            remaining[i],
            extracted_ids
        )

        if structured:
            extracted_data.append(structured)

            logs.append({
                "id": structured["id"],
                "title": structured["meta"]["title"],
                "status": status,
                "timestamp": structured["extraction_info"]["timestamp"]
            })

        progress.progress((i + 1) / total)
        time.sleep(1)

    save_json(EXTRACTED_PATH, extracted_data)
    save_json(LOG_PATH, logs)

    st.success("Batch completed!")

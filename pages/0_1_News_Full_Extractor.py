

# # pages/News_Batch_Extractor.py

# import streamlit as st
# import json
# import requests
# from bs4 import BeautifulSoup
# from datetime import datetime
# import hashlib
# import os
# import time

# st.set_page_config(page_title="Batch News Extractor", layout="wide")
# st.title("📰 Batch News Extractor (Resume Enabled)")

# DATA_PATH = "data/news_dataset_new.json"
# EXTRACTED_PATH = "data/news_extracted.json"
# LOG_PATH = "data/logs.json"


# # ---------------------------
# # Utilities
# # ---------------------------

# def generate_id(article):
#     raw = article["title"] + article["published"] + article["link"]
#     return hashlib.md5(raw.encode()).hexdigest()


# def load_json(path, default):
#     if os.path.exists(path):
#         with open(path, "r", encoding="utf-8") as f:
#             return json.load(f)
#     return default


# def save_json(path, data):
#     with open(path, "w", encoding="utf-8") as f:
#         json.dump(data, f, indent=4)


# def extract_article(url):
#     try:
#         headers = {"User-Agent": "Mozilla/5.0"}
#         response = requests.get(url, headers=headers, timeout=10)

#         soup = BeautifulSoup(response.text, "html.parser")
#         paragraphs = [p.get_text().strip() for p in soup.find_all("p")]
#         clean_text = "\n".join(paragraphs)

#         return {
#             "raw_html": None,  # optional (can disable to save space)
#             "clean_text": clean_text,
#             "paragraphs": paragraphs,
#             "word_count": len(clean_text.split())
#         }, "success"

#     except Exception as e:
#         return None, str(e)


# # ---------------------------
# # Load Data
# # ---------------------------

# news_data = load_json(DATA_PATH, [])
# extracted_data = load_json(EXTRACTED_PATH, [])
# logs = load_json(LOG_PATH, [])

# extracted_ids = {item["id"] for item in extracted_data}

# st.write(f"Total Original Articles: {len(news_data)}")
# st.write(f"Already Extracted: {len(extracted_ids)}")
# st.write(f"Remaining: {len(news_data) - len(extracted_ids)}")


# # ---------------------------
# # Batch Config
# # ---------------------------

# batch_size = st.number_input("Batch Size", 1, 100, 5)
# sleep_time = st.number_input("Delay Between Requests (sec)", 0.0, 5.0, 1.0)


# # ---------------------------
# # Extraction Button
# # ---------------------------

# if st.button("🚀 Start Batch Extraction"):

#     progress_bar = st.progress(0)
#     new_extracted = []

#     remaining_articles = [
#         article for article in news_data
#         if generate_id(article) not in extracted_ids
#     ]

#     total = min(batch_size, len(remaining_articles))

#     for i in range(total):
#         article = remaining_articles[i]
#         article_id = generate_id(article)

#         content, status = extract_article(article["decoded_url"])

#         structured = {
#             "id": article_id,
#             "meta": {
#                 "title": article["title"],
#                 "source": article["source"],
#                 "published": article["published"],
#                 "company": article["company_name"],
#                 "esg_score": article["esg_score"],
#             },
#             "content": content,
#             "extraction_info": {
#                 "timestamp": datetime.utcnow().isoformat(),
#                 "status": status
#             }
#         }

#         new_extracted.append(structured)

#         logs.append({
#             "id": article_id,
#             "title": article["title"],
#             "timestamp": datetime.utcnow().isoformat(),
#             "status": status
#         })

#         progress_bar.progress((i + 1) / total)
#         time.sleep(sleep_time)

#     # Append and save incrementally
#     extracted_data.extend(new_extracted)
#     save_json(EXTRACTED_PATH, extracted_data)
#     save_json(LOG_PATH, logs)

#     st.success(f"Batch Completed: {len(new_extracted)} articles processed.")

# # pages/News_Full_Extractor.py

# import streamlit as st
# import json
# import pandas as pd
# import requests
# from bs4 import BeautifulSoup
# from datetime import datetime
# import os

# st.set_page_config(page_title="Full News Extractor", layout="wide")
# st.title("📰 Full News Extraction & Hierarchical JSON Builder")

# DATA_PATH = "data/news_dataset_new.json"
# EXTRACTED_PATH = "data/news_extracted.json"
# LOG_PATH = "data/logs.json"


# # -------------------------
# # Load Original Dataset
# # -------------------------
# @st.cache_data
# def load_original():
#     with open(DATA_PATH, "r", encoding="utf-8") as f:
#         return json.load(f)

# news_data = load_original()

# st.write(f"Total Articles: {len(news_data)}")


# # -------------------------
# # Helper: Extract Full Text
# # -------------------------
# def extract_full_article(url):
#     try:
#         response = requests.get(url, timeout=10)
#         soup = BeautifulSoup(response.text, "html.parser")

#         paragraphs = [p.get_text().strip() for p in soup.find_all("p")]
#         clean_text = "\n".join(paragraphs)

#         return {
#             "raw_html": response.text,
#             "clean_text": clean_text,
#             "paragraphs": paragraphs,
#             "word_count": len(clean_text.split())
#         }, "success"

#     except Exception as e:
#         return None, str(e)


# # -------------------------
# # Save JSON Utility
# # -------------------------
# def save_json(path, data):
#     with open(path, "w", encoding="utf-8") as f:
#         json.dump(data, f, indent=4)


# # -------------------------
# # Extraction Button
# # -------------------------
# if st.button("🚀 Extract All Articles"):

#     extracted_articles = []
#     logs = []

#     for article in news_data:

#         meta = {
#             "title": article["title"],
#             "source": article["source"],
#             "published": article["published"],
#             "company": article["company_name"],
#             "company_code": article["company_code"],
#             "esg_score": article["esg_score"],
#             "keyword": article["keyword"],
#         }

#         content, status = extract_full_article(article["decoded_url"])

#         structured = {
#             "meta": meta,
#             "content": content,
#             "extraction_info": {
#                 "timestamp": datetime.utcnow().isoformat(),
#                 "status": status
#             }
#         }

#         extracted_articles.append(structured)

#         logs.append({
#             "title": article["title"],
#             "timestamp": datetime.utcnow().isoformat(),
#             "status": status
#         })

#     # Save extracted data
#     save_json(EXTRACTED_PATH, extracted_articles)

#     # Append logs history
#     if os.path.exists(LOG_PATH):
#         with open(LOG_PATH, "r") as f:
#             existing_logs = json.load(f)
#     else:
#         existing_logs = []

#     existing_logs.extend(logs)
#     save_json(LOG_PATH, existing_logs)

#     st.success("Extraction Completed & Saved!")


# # -------------------------
# # Load & Visualize Extracted JSON
# # -------------------------
# if os.path.exists(EXTRACTED_PATH):

#     with open(EXTRACTED_PATH, "r") as f:
#         extracted_data = json.load(f)

#     st.subheader("📊 Hierarchical JSON Preview")

#     st.json(extracted_data[0])  # Show first article hierarchy

#     # Statistics
#     word_counts = [
#         item["content"]["word_count"]
#         for item in extracted_data
#         if item["content"]
#     ]

#     st.subheader("📈 Statistics")
#     st.write("Total Extracted:", len(extracted_data))
#     st.write("Average Word Count:", sum(word_counts)/len(word_counts) if word_counts else 0)
#     st.write("Max Word Count:", max(word_counts) if word_counts else 0)

#     df_stats = pd.DataFrame(word_counts, columns=["Word Count"])
#     st.bar_chart(df_stats)
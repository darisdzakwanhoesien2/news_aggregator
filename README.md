Below is a **complete, ready-to-run Streamlit mini-app** that:

1. Fetches the latest news from
   **[https://berita-indo-api-next.vercel.app/api/antara-news/terkini](https://berita-indo-api-next.vercel.app/api/antara-news/terkini)**
2. Saves the data into your **existing JSON file** (append or update)
3. Displays the news inside the Streamlit UI
4. Organizes your project directory cleanly

---

References 
1. https://github.com/satyawikananda/berita-indo-api/blob/5af2ef203c11e9abeda675572e4affa3489439d4/src/app/api/route.ts#L4C29-L4C29
2. https://github.com/farizdotid/DAFTAR-API-LOKAL-INDONESIA/blob/master/README.en.md
3. https://chatgpt.com/c/6931ab83-4c68-832c-81a0-4abdc855294b

# ✅ **Project Directory Structure**

```
news_scraper/
│
├── app.py
├── data/
│   └── news.json         # will be created automatically
└── requirements.txt
```


https://chatgpt.com/c/697820fe-225c-832c-8337-c20a541349a2

https://chatgpt.com/c/697820fe-225c-832c-8337-c20a541349a2


---

# ✅ **Streamlit Scraper App (`app.py`)**

```python

```

---

# ✅ **How It Works**

### ✔ Fetch news

API returns format like:



### ✔ Store in `data/news.json`

Stored format:

```json
{
  "last_updated": "2025-12-04T17:00:00",
  "news": [
    { "title": "...", "link": "...", "content": "...", "isoDate": "..." }
  ]
}
```

### ✔ Avoid duplicates

It uses the **article link** as a unique ID.

---

# 🔥 If you want a version that automatically fetches every X minutes

I can add `st_autorefresh()` or a background cron loop.

---

If you want to **scrape multiple news sources** (CNN Indonesia, CNBC, Kompas, etc.), I can extend this into a full news dashboard.
# news_aggregator

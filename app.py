# app.py
import streamlit as st
import requests
import json
from pathlib import Path
from datetime import datetime, date, timedelta
import pandas as pd
import matplotlib.pyplot as plt
import io
import smtplib
from email.message import EmailMessage

# ----------------------
# CONFIG / PATHS
# ----------------------
BASE_URL = "https://berita-indo-api-next.vercel.app"
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
NEWS_PATH = DATA_DIR / "news.json"
LOG_PATH = DATA_DIR / "logs.jsonl"
DAILY_SUMMARY_DIR = DATA_DIR / "daily_summary"
DAILY_SUMMARY_DIR.mkdir(exist_ok=True)

# ----------------------
# NEWS SOURCES (from your Next.js map)
# ----------------------
NEWS_SOURCES = {
    "CNN News": {"all": "/api/cnn-news/", "listType": ["nasional","internasional","ekonomi","olahraga","teknologi","hiburan","gaya-hidup"]},
    "CNBC News": {"all": "/api/cnbc-news/","listType":["market","news","entrepreneur","syariah","tech","lifestyle"]},
    "Republika News": {"all": "/api/republika-news/","listType":["news","nusantara","khazanah","islam-digest","internasional","ekonomi","sepakbola","leisure"]},
    "Tempo News": {"all": "/api/tempo-news/","listType":["nasional","bisnis","metro","dunia","bola","sport","cantik","tekno","otomotif","nusantara"]},
    "Antara News": {"listType":["terkini","top-news","politik","hukum","ekonomi","metro","sepakbola","olahraga","humaniora","lifestyle","hiburan","dunia","infografik","tekno","otomotif","warta-bumi","rilis-pers"]},
    "Okezone News": {"all": "/api/okezone-news","listType":["breaking","sport","economy","lifestyle","celebrity","bola","techno"]},
    "BBC News": {"all": "/api/bbc-news","listType":["dunia","berita_indonesia","olahraga","majalah","multimedia"]},
    "Kumparan News": {"all": "/api/kumparan-news"},
    "Tribun News": {"all": "/api/tribun-news","listType":["bisnis","superskor","sport","seleb","lifestyle","travel","parapuan","otomotif","techno","ramadan"]},
    "Zetizen Jawapos News": {"all": "/api/zetizen-jawapos-news","listType":["book","movie","music","tv-series","beauty","trend","food-and-traveling","games","otomodif","sport-and-health","after-school","career-coach","dear-you","get-a-life","scholarship-info","science","techno","zetizen-national-challenge"]},
    "Vice": {"all": "/api/vice-news"},
    "Suara News": {"all": "/api/suara-news","listType":["news","bisnis","lifestyle","entertainment","otomotif","tekno","health","mostpopular","wawancara","pressrelease"]},
    "VOA Indonesia": {"all": "/api/voa-news"},
}

# ----------------------
# Utilities: load/save
# ----------------------
def load_news():
    if NEWS_PATH.exists():
        with open(NEWS_PATH, "r", encoding="utf8") as f:
            return json.load(f)
    return {"last_update": None, "articles": []}

def save_news(payload):
    NEWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(NEWS_PATH, "w", encoding="utf8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

def append_log(entry: dict):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def read_logs():
    if not LOG_PATH.exists():
        return []
    with open(LOG_PATH, "r", encoding="utf8") as f:
        return [json.loads(line) for line in f if line.strip()]

def remove_duplicates_by_url(articles):
    seen = set()
    out = []
    for a in articles:
        url = a.get("link") or a.get("url") or a.get("guid")
        if not url:
            # fallback unique key built from title+isoDate
            url = f"{a.get('title','')}-{a.get('isoDate','')}"
        if url not in seen:
            seen.add(url)
            out.append(a)
    return out

# ----------------------
# Fetch single endpoint
# ----------------------
def fetch_api(api_url, timeout=12):
    r = requests.get(api_url, timeout=timeout)
    r.raise_for_status()
    return r.json()

# ----------------------
# Normalize API response -> list of articles
# ----------------------
def extract_articles_from_response(resp):
    # Many endpoints use "data" key
    if isinstance(resp, dict):
        if "data" in resp and isinstance(resp["data"], list):
            return resp["data"]
        # sometimes api returns { status: ..., articles: [...] }
        if "articles" in resp and isinstance(resp["articles"], list):
            return resp["articles"]
        # sometimes it's already the list
    if isinstance(resp, list):
        return resp
    return []

# ----------------------
# Daily summary writer
# ----------------------
def write_daily_summary(date_obj: date, summary: dict):
    p = DAILY_SUMMARY_DIR / f"{date_obj.isoformat()}.json"
    with open(p, "w", encoding="utf8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    return p

# ----------------------
# Email (SMTP) helper
# ----------------------
def send_email_summary(smtp_host, smtp_port, smtp_user, smtp_password, to_email, subject, body_text, attachment_bytes=None, attachment_name="summary.json"):
    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body_text)

    if attachment_bytes:
        msg.add_attachment(attachment_bytes, maintype="application", subtype="json", filename=attachment_name)

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as smtp:
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(msg)

# ----------------------
# Slack (webhook) helper
# ----------------------
def post_slack_webhook(webhook_url, message_text):
    payload = {"text": message_text}
    r = requests.post(webhook_url, json=payload, timeout=10)
    r.raise_for_status()
    return r

# ----------------------
# Aggregation helpers for visuals/reports
# ----------------------
def logs_to_dataframe(logs):
    if not logs:
        return pd.DataFrame()
    df = pd.DataFrame(logs)
    # coerce timestamp to datetime
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date"] = df["timestamp"].dt.date
    return df

def daily_aggregate_from_logs(df_logs):
    if df_logs.empty:
        return pd.DataFrame()
    agg = df_logs.groupby("date").agg({
        "incoming": "sum",
        "added": "sum",
        "duplicates": "sum",
        "total_after": "last"
    }).reset_index()
    return agg

def per_source_aggregate(df_logs):
    if df_logs.empty:
        return pd.DataFrame()
    agg = df_logs.groupby(["source", df_logs["timestamp"].dt.date]).agg({
        "incoming":"sum","added":"sum","duplicates":"sum"
    }).reset_index().rename(columns={"timestamp":"date"})
    return agg

# ----------------------
# Streamlit UI
# ----------------------
st.set_page_config(page_title="News Scraper + 6h Auto-refresh + Analytics", layout="wide")
st.title("📰 Indonesia News Scraper — Auto-refresh every 6 hours")

# LEFT: controls; RIGHT: analytics & logs
col1, col2 = st.columns([1,2])

with col1:
    st.header("Controls")
    source = st.selectbox("Source", list(NEWS_SOURCES.keys()))
    info = NEWS_SOURCES[source]
    category = None
    if "listType" in info:
        category = st.selectbox("Category", info["listType"])
    api_path = info.get("all") or f"/api/{source.lower().replace(' ','-')}-news/"
    api_url = f"{BASE_URL}{api_path}"
    if category:
        # api might expect trailing slash before category; earlier templates used pattern /api/<x>/<category>
        if not api_url.endswith("/"):
            api_url = api_url + "/"
        api_url = f"{api_url}{category}"

    st.write("API URL:", api_url)

    # Manual fetch controls
    if st.button("Fetch & Save (manual)"):
        try:
            resp = fetch_api(api_url)
            new_articles = extract_articles_from_response(resp)
            stored = load_news()
            before = len(stored["articles"])
            stored["articles"].extend(new_articles)
            # dedupe
            stored["articles"] = remove_duplicates_by_url(stored["articles"])
            after = len(stored["articles"])
            added = after - before
            incoming = len(new_articles)
            duplicates = incoming - added if incoming >= added else 0
            stored["last_update"] = datetime.now().isoformat()
            save_news(stored)

            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "source": source,
                "category": category or "all",
                "incoming": incoming,
                "added": added,
                "duplicates": duplicates,
                "total_after": after
            }
            append_log(log_entry)
            st.success(f"Fetched {incoming} items, added {added}, duplicates {duplicates}. Total articles: {after}")
        except Exception as e:
            st.error(f"Fetch error: {e}")

    st.markdown("---")
    # Fetch All button (iterate sources/categories)
    if st.button("Fetch All Configured Sources (may be slow)"):
        overall_added = 0
        overall_incoming = 0
        errors = []
        stored = load_news()
        before_all = len(stored["articles"])

        # iterate all sources; if they have listType, fetch each category
        for sname, sinfo in NEWS_SOURCES.items():
            paths = []
            if "listType" in sinfo:
                for t in sinfo["listType"]:
                    base = sinfo.get("all") or f"/api/{sname.lower().replace(' ','-')}-news/"
                    if not base.endswith("/"):
                        base = base + "/"
                    paths.append(f"{BASE_URL}{base}{t}")
            else:
                p = sinfo.get("all")
                if p:
                    paths.append(f"{BASE_URL}{p}")
            for p in paths:
                try:
                    resp = fetch_api(p)
                    arr = extract_articles_from_response(resp)
                    incoming = len(arr)
                    overall_incoming += incoming
                    stored["articles"].extend(arr)
                    # small pause not included — if you hit rate limits, add time.sleep
                    append_log({
                        "timestamp": datetime.now().isoformat(),
                        "source": sname,
                        "category": p.split("/")[-1] or "all",
                        "incoming": incoming,
                        "added": None,   # will compute after dedupe
                        "duplicates": None,
                        "total_after": None
                    })
                except Exception as e:
                    errors.append({"source": sname, "path": p, "error": str(e)})
        # dedupe once
        stored["articles"] = remove_duplicates_by_url(stored["articles"])
        after_all = len(stored["articles"])
        overall_added = after_all - before_all
        stored["last_update"] = datetime.now().isoformat()
        save_news(stored)

        # patch earlier logs entries without added/duplicates/total_after
        # Simple approach: append a final log line summarizing fetch-all
        append_log({
            "timestamp": datetime.now().isoformat(),
            "source": "FETCH_ALL_SUMMARY",
            "category": "multiple",
            "incoming": overall_incoming,
            "added": overall_added,
            "duplicates": overall_incoming - overall_added,
            "total_after": after_all
        })

        st.success(f"Fetch All finished. incoming={overall_incoming} added={overall_added}. Errors: {len(errors)}")
        if errors:
            st.warning(f"Some fetches failed; see console / logs for details.")
            st.json(errors[:5])

    st.markdown("---")
    # Auto-refresh (6 hours)
    st.subheader("Auto-refresh (client open required)")
    st.write("This page will auto-refresh every 6 hours while open in your browser.")
    # Try to use st_autorefresh if available, else use JS fallback
    try:
        # streamlit-autorefresh is a tiny helper package. If installed, use it.
        from streamlit_autorefresh import st_autorefresh
        count = st_autorefresh(interval=6*60*60*1000, key="auto_refresh_6h")  # milliseconds
        st.write("Auto-refresh using `streamlit_autorefresh` enabled.")
    except Exception:
        # Fallback: client-side JS reload every 6 hours
        js_reload_ms = 6 * 60 * 60 * 1000
        st.components.v1.html(f"""
            <script>
            // Fallback auto-refresh: reload page every 6 hours (21600000 ms)
            setTimeout(() => {{
                window.location.reload();
            }}, {js_reload_ms});
            </script>
            <div style="font-size:0.9rem;color:gray">Auto-refresh fallback enabled (JS). Keep this tab open.</div>
        """, height=60)

    st.markdown("---")
    # DAILY SUMMARY: options & senders
    st.subheader("Daily summary (generate & send)")
    send_email_enable = st.checkbox("Enable Email delivery of daily summary", value=False, key="email_enable")
    if send_email_enable:
        smtp_host = st.text_input("SMTP host (e.g. smtp.gmail.com)", key="smtp_host")
        smtp_port = st.number_input("SMTP port (SSL)", value=465, key="smtp_port")
        smtp_user = st.text_input("SMTP username (from)", key="smtp_user")
        smtp_pass = st.text_input("SMTP password", type="password", key="smtp_pass")
        email_to = st.text_input("Send to (recipient email)", key="email_to")
    send_slack_enable = st.checkbox("Enable Slack webhook delivery", value=False, key="slack_enable")
    if send_slack_enable:
        slack_webhook = st.text_input("Slack webhook URL", key="slack_webhook")

    if st.button("Generate daily summary now"):
        # read logs, compute today's summary
        logs = read_logs()
        df_logs = logs_to_dataframe(logs)
        today = date.today()
        df_today = df_logs[df_logs["date"] == today] if not df_logs.empty else pd.DataFrame()
        total_incoming = int(df_today["incoming"].sum()) if not df_today.empty else 0
        total_added = int(df_today["added"].sum()) if not df_today.empty else 0
        total_duplicates = int(df_today["duplicates"].sum()) if not df_today.empty else 0
        per_source = df_today.groupby("source").agg({"incoming":"sum","added":"sum","duplicates":"sum"}).to_dict(orient="index") if not df_today.empty else {}

        summary = {
            "date": today.isoformat(),
            "total_incoming": int(total_incoming),
            "total_added": int(total_added),
            "total_duplicates": int(total_duplicates),
            "per_source": per_source,
            "generated_at": datetime.now().isoformat()
        }
        # write summary json
        summary_path = write_daily_summary(today, summary)
        st.success(f"Daily summary written: {summary_path}")
        st.json(summary)

        # send if enabled
        if send_email_enable:
            try:
                with open(summary_path, "rb") as f:
                    bytes_payload = f.read()
                send_email_summary(smtp_host, int(smtp_port), smtp_user, smtp_pass, email_to,
                                   f"News Scraper Daily Summary {today.isoformat()}",
                                   f"Daily summary for {today.isoformat()}. See attachment.",
                                   attachment_bytes=bytes_payload,
                                   attachment_name=summary_path.name)
                st.success("Email sent.")
            except Exception as e:
                st.error(f"Email send failed: {e}")

        if send_slack_enable:
            try:
                post_slack_webhook(slack_webhook, f"Daily summary for {today.isoformat()}: incoming={total_incoming}, added={total_added}, duplicates={total_duplicates}")
                st.success("Slack notification posted.")
            except Exception as e:
                st.error(f"Slack send failed: {e}")

with col2:
    st.header("Analytics & Logs")
    logs = read_logs()
    if not logs:
        st.info("No logs yet. Perform a fetch to generate logs.")
    else:
        df_logs = logs_to_dataframe(logs)
        st.subheader("Recent log entries")
        # show last 50 logs
        st.dataframe(pd.DataFrame(logs)[::-1].head(50))

        # Daily aggregated chart (incoming / added / duplicates)
        st.subheader("Daily aggregated (incoming / added / duplicates)")
        df_daily = daily_aggregate_from_logs(df_logs)
        if df_daily.empty:
            st.info("No aggregated data yet.")
        else:
            # plot with matplotlib (single plot per rule)
            fig1, ax1 = plt.subplots(figsize=(9,3))
            ax1.plot(df_daily["date"], df_daily["incoming"], label="incoming")
            ax1.plot(df_daily["date"], df_daily["added"], label="added")
            ax1.plot(df_daily["date"], df_daily["duplicates"], label="duplicates")
            ax1.set_xlabel("date")
            ax1.set_ylabel("count")
            ax1.legend()
            ax1.set_title("Daily trend: incoming / added / duplicates")
            st.pyplot(fig1)

        # Per-source analytics (last N days)
        st.subheader("Per-source recent analytics (last 14 days)")
        cutoff = date.today() - timedelta(days=14)
        df_recent = df_logs[df_logs["timestamp"] >= pd.Timestamp(cutoff)]
        if df_recent.empty:
            st.info("No recent logs for per-source analytics.")
        else:
            ps = df_recent.groupby("source").agg({"incoming":"sum","added":"sum","duplicates":"sum"}).sort_values("incoming", ascending=False)
            st.dataframe(ps)

        # Graph: new vs duplicate trend (stacked bar by day)
        st.subheader("New vs Duplicate trend (stacked bars)")
        if df_daily.empty:
            st.info("No daily data.")
        else:
            fig2, ax2 = plt.subplots(figsize=(9,3))
            ax2.bar(df_daily["date"], df_daily["added"], label="added")
            ax2.bar(df_daily["date"], df_daily["duplicates"], bottom=df_daily["added"], label="duplicates")
            ax2.set_xlabel("date")
            ax2.set_ylabel("count")
            ax2.legend()
            st.pyplot(fig2)

# ----------------------
# On-load: Optionally perform a fetch for the selected source (quiet)
# ----------------------
# This block will not run automatically; only when user presses buttons or auto-refresh reloads page.
st.markdown("---")
st.caption("Notes: Auto-refresh will reload this page every 6 hours while open. The app stores logs to data/logs.jsonl and news in data/news.json. Email / Slack delivery requires valid credentials / webhook URLs.")


import os
from newspaper import Article
from datetime import datetime

RAW_HTML_DIR = "data/raw_html"
os.makedirs(RAW_HTML_DIR, exist_ok=True)


def extract_article(article_id, url):
    try:
        article = Article(url)
        article.download()
        article.parse()

        html_path = f"{RAW_HTML_DIR}/{article_id}.html"

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(article.html)

        clean_text = article.text
        word_count = len(clean_text.split())

        status = "success" if word_count > 100 else "failed_low_content"

        return {
            "raw_html_path": html_path,
            "clean_text": clean_text,
            "word_count": word_count,
        }, status

    except Exception as e:
        return None, f"error: {str(e)}"
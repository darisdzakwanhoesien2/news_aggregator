import hashlib
from datetime import datetime
from extractor.redirect_resolver import resolve_google_news_url
from extractor.article_extractor import extract_article


def generate_id(article):
    raw = article["title"] + article["published"] + article["link"]
    return hashlib.md5(raw.encode()).hexdigest()


def process_article(article, extracted_ids):
    article_id = generate_id(article)

    if article_id in extracted_ids:
        return None, "skipped"

    resolved_url = resolve_google_news_url(article["decoded_url"])

    if not resolved_url:
        return {
            "id": article_id,
            "meta": article,
            "content": None,
            "extraction_info": {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "failed_redirect"
            }
        }, "failed"

    content, status = extract_article(article_id, resolved_url)

    structured = {
        "id": article_id,
        "meta": {
            "title": article["title"],
            "source": article["source"],
            "published": article["published"],
            "company": article["company_name"],
            "esg_score": article["esg_score"]
        },
        "content": content,
        "extraction_info": {
            "timestamp": datetime.utcnow().isoformat(),
            "status": status,
            "resolved_url": resolved_url
        }
    }

    return structured, status
from playwright.sync_api import sync_playwright
from datetime import datetime
import re

def _extract_metric(article, keyword):
    """
    Extract numeric metric from aria-label, e.g. '12 Likes'
    """
    try:
        btn = article.query_selector(f"div[aria-label*='{keyword}']")
        if not btn:
            return 0
        text = btn.get_attribute("aria-label")
        return int(re.search(r"\d+", text).group())
    except Exception:
        return 0


from utils.x_text_metrics import extract_metrics_from_text

def fetch_tweets_playwright(username, scrolls=5, existing_ids=None, source_type="ngo"):
    existing_ids = existing_ids or set()
    url = f"https://x.com/{username}"
    tweets = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(url, timeout=60000)
        page.wait_for_timeout(5000)

        for _ in range(scrolls):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(2500)

        articles = page.query_selector_all("article")

        for art in articles:
            try:
                link = art.query_selector("a[href*='/status/']")
                if not link:
                    continue

                href = link.get_attribute("href")
                post_id = href.split("/")[-1]

                if post_id in existing_ids:
                    continue

                text = art.inner_text()

                metrics = extract_metrics_from_text(text)

                tweets.append({
                    "platform": "x",
                    "username": username,
                    "post_id": post_id,
                    "url": f"https://x.com{href}",
                    "content": text,
                    "likes": metrics["likes"],
                    "comments": metrics["comments"],
                    "shares": metrics["shares"],
                    "views": metrics["views"],
                    "timestamp": None,
                    "scraped_at": datetime.utcnow().isoformat(),
                    "source_type": source_type
                })
            except Exception:
                continue

        browser.close()

    return tweets

def fetch_tweets_incremental(
    username: str,
    max_scrolls: int = 30,
    existing_ids: set[str] | None = None,
    source_type: str = "ngo",
):
    """
    Incremental X scraper:
    - Skips existing posts
    - Scrolls until no new posts are found
    """
    existing_ids = existing_ids or set()
    url = f"https://x.com/{username}"

    new_posts = []
    seen_ids = set(existing_ids)
    no_new_scrolls = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(url, timeout=60000)
        page.wait_for_timeout(5000)

        for scroll in range(max_scrolls):
            articles = page.query_selector_all("article")

            new_found_this_scroll = 0

            for art in articles:
                try:
                    link = art.query_selector("a[href*='/status/']")
                    if not link:
                        continue

                    href = link.get_attribute("href")
                    post_id = href.split("/")[-1]

                    # 🔁 SKIP ALREADY SCRAPED POSTS
                    if post_id in seen_ids:
                        continue

                    text = art.inner_text()
                    metrics = extract_metrics_from_text(text)

                    new_posts.append({
                        "platform": "x",
                        "username": username,
                        "post_id": post_id,
                        "url": f"https://x.com{href}",
                        "content": text,
                        "likes": metrics["likes"],
                        "comments": metrics["comments"],
                        "shares": metrics["shares"],
                        "views": metrics.get("views"),
                        "timestamp": None,  # backfilled later
                        "scraped_at": datetime.utcnow().isoformat(),
                        "source_type": source_type,
                        "metrics_source": (
                            "text" if any(metrics.values()) else "unavailable"
                        ),
                    })

                    seen_ids.add(post_id)
                    new_found_this_scroll += 1

                except Exception:
                    continue

            # 🛑 STOP CONDITION
            if new_found_this_scroll == 0:
                no_new_scrolls += 1
            else:
                no_new_scrolls = 0

            if no_new_scrolls >= 3:
                break

            # Scroll down
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(2500)

        browser.close()

    return new_posts


# def fetch_tweets_playwright(username, scrolls=5, source_type="ngo"):
#     url = f"https://x.com/{username}"
#     tweets = []

#     with sync_playwright() as p:
#         browser = p.chromium.launch(headless=True)
#         page = browser.new_page()

#         page.goto(url, timeout=60000)
#         page.wait_for_timeout(5000)

#         for _ in range(scrolls):
#             page.mouse.wheel(0, 4000)
#             page.wait_for_timeout(2500)

#         articles = page.query_selector_all("article")

#         for art in articles:
#             try:
#                 link = art.query_selector("a[href*='/status/']")
#                 if not link:
#                     continue

#                 href = link.get_attribute("href")
#                 tweet_id = href.split("/")[-1]

#                 content = art.inner_text()

#                 tweets.append({
#                     "platform": "x",
#                     "username": username,
#                     "post_id": tweet_id,
#                     "url": f"https://x.com{href}",
#                     "content": content,
#                     "likes": _extract_metric(art, "Like"),
#                     "comments": _extract_metric(art, "Reply"),
#                     "shares": _extract_metric(art, "Repost"),
#                     "views": None,
#                     "timestamp": None,
#                     "scraped_at": datetime.utcnow().isoformat(),
#                     "source_type": source_type
#                 })
#             except Exception:
#                 continue

#         browser.close()

#     return tweets

# from playwright.sync_api import sync_playwright
# from datetime import datetime
# import time

# def fetch_tweets_playwright(username, scrolls=3, source_type="ngo"):
#     url = f"https://x.com/{username}"
#     tweets = []

#     with sync_playwright() as p:
#         browser = p.chromium.launch(headless=True)
#         page = browser.new_page()
#         page.goto(url, timeout=60000)
#         page.wait_for_timeout(5000)

#         for _ in range(scrolls):
#             page.mouse.wheel(0, 3000)
#             page.wait_for_timeout(3000)

#         articles = page.query_selector_all("article")

#         for art in articles:
#             try:
#                 content = art.inner_text()
#                 link = art.query_selector("a[href*='/status/']")
#                 if not link:
#                     continue

#                 href = link.get_attribute("href")
#                 tweet_id = href.split("/")[-1]

#                 tweets.append({
#                     "platform": "x",
#                     "username": username,
#                     "post_id": tweet_id,
#                     "url": f"https://x.com{href}",
#                     "content": content,
#                     "likes": None,
#                     "comments": None,
#                     "shares": None,
#                     "views": None,
#                     "timestamp": None,
#                     "scraped_at": datetime.utcnow().isoformat(),
#                     "source_type": source_type
#                 })
#             except Exception:
#                 continue

#         browser.close()

#     return tweets
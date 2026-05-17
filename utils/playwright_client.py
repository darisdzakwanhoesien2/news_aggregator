from playwright.sync_api import sync_playwright
from datetime import datetime
import time

def fetch_posts_playwright(username, scrolls=5):
    url = f"https://www.instagram.com/{username}/"

    posts = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(url, timeout=60000)
        page.wait_for_timeout(5000)

        for _ in range(scrolls):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(3000)

        links = page.query_selector_all("article a")

        seen = set()
        for link in links:
            href = link.get_attribute("href")
            if href and href.startswith("/p/") and href not in seen:
                seen.add(href)
                posts.append({
                    "username": username,
                    "url": f"https://www.instagram.com{href}",
                    "shortcode": href.strip("/").split("/")[-1],
                    "scraped_at": datetime.utcnow().isoformat()
                })

        browser.close()

    return posts
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re


def resolve_google_news_url(url):
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=15,
            allow_redirects=True
        )

        final_url = response.url

        # If already external
        if "google.com" not in urlparse(final_url).netloc:
            return final_url

        soup = BeautifulSoup(response.text, "html.parser")

        # Meta refresh
        meta = soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
        if meta:
            content = meta.get("content", "")
            match = re.search(r"url=['\"]?(.*?)['\"]?$", content)
            if match:
                return match.group(1)

        # Anchor fallback
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http") and "google.com" not in href:
                return href

        return None

    except Exception:
        return None
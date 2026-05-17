import os
import re
import requests
from dotenv import load_dotenv
from urllib.parse import urlparse

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
BASE_URL = "https://www.googleapis.com/youtube/v3"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def has_youtube_api_key() -> bool:
    return bool((YOUTUBE_API_KEY or "").strip())


def _extract_channel_id_from_text(text: str) -> str | None:
    patterns = [
        r"https://www\.youtube\.com/channel/(UC[a-zA-Z0-9_-]{20,})",
        r'"externalId":"(UC[a-zA-Z0-9_-]{20,})"',
        r'"channelId":"(UC[a-zA-Z0-9_-]{20,})"',
        r'"browseId":"(UC[a-zA-Z0-9_-]{20,})"',
        r'"canonicalBaseUrl":"/channel/(UC[a-zA-Z0-9_-]{20,})"',
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)

    return None


def _extract_identifier(url: str) -> str | None:
    match = re.search(r"youtube\.com/(?:@|c/|user/)([^/?]+)", url)
    if match:
        return match.group(1)

    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parts and parts[0] not in {"watch", "shorts", "playlist", "embed"}:
        return parts[-1].lstrip("@")

    return None


def _resolve_via_api(identifier: str) -> str | None:
    if not has_youtube_api_key():
        return None

    params = {
        "part": "id",
        "forHandle": identifier.lstrip("@"),
        "key": YOUTUBE_API_KEY,
    }

    try:
        resp = requests.get(
            f"{BASE_URL}/channels",
            params=params,
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                return items[0]["id"]
    except requests.RequestException:
        pass

    params = {
        "part": "snippet",
        "q": identifier,
        "type": "channel",
        "maxResults": 1,
        "key": YOUTUBE_API_KEY,
    }

    try:
        resp = requests.get(
            f"{BASE_URL}/search",
            params=params,
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                item = items[0]
                return item.get("snippet", {}).get("channelId")
    except requests.RequestException:
        pass

    return None


def _resolve_via_html(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    channel_id = _extract_channel_id_from_text(resp.text)
    if channel_id:
        return channel_id

    if resp.url and resp.url != url:
        match = re.search(r"/channel/(UC[a-zA-Z0-9_-]{20,})", resp.url)
        if match:
            return match.group(1)

    return None


def get_channel_id_from_url(url: str) -> str | None:
    """
    Resolve YouTube Channel ID from:
    - @handle URLs
    - /channel/ URLs
    - /c/ custom URLs
    - /user/ legacy URLs
    """

    raw = (url or "").strip()
    if not raw:
        return None

    # Case 1 — raw channel ID
    match = re.fullmatch(r"(UC[a-zA-Z0-9_-]{20,})", raw)
    if match:
        return match.group(1)

    # Case 2 — URL already contains a channel ID
    match = re.search(r"/channel/(UC[a-zA-Z0-9_-]{20,})", raw)
    if match:
        return match.group(1)

    identifier = _extract_identifier(raw)
    if identifier:
        channel_id = _resolve_via_api(identifier)
        if channel_id:
            return channel_id

    if raw.startswith("http"):
        channel_id = _resolve_via_html(raw)
        if channel_id:
            return channel_id

    return None

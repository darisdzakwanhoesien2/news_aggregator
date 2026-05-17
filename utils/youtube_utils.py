import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
BASE_URL = "https://www.googleapis.com/youtube/v3"


def get_channel_id_from_url(url: str) -> str | None:
    """
    Resolve YouTube Channel ID from:
    - @handle URLs
    - /channel/ URLs
    - /c/ custom URLs
    - /user/ legacy URLs
    """

    # Case 1 — already channel ID
    match = re.search(r"/channel/(UC[a-zA-Z0-9_-]{20,})", url)
    if match:
        return match.group(1)

    # Extract identifier
    match = re.search(r"youtube\.com/(?:@|c/|user/)([^/?]+)", url)
    if not match:
        return None

    identifier = match.group(1)

    # Try handle resolution first
    params = {
        "part": "id",
        "forHandle": identifier,
        "key": YOUTUBE_API_KEY,
    }

    resp = requests.get(f"{BASE_URL}/channels", params=params)
    if resp.status_code == 200:
        items = resp.json().get("items", [])
        if items:
            return items[0]["id"]

    # Fallback: search by name
    params = {
        "part": "snippet",
        "q": identifier,
        "type": "channel",
        "maxResults": 1,
        "key": YOUTUBE_API_KEY,
    }

    resp = requests.get(f"{BASE_URL}/search", params=params)
    if resp.status_code == 200:
        items = resp.json().get("items", [])
        if items:
            return items[0]["snippet"]["channelId"]

    return None

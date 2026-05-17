import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")
BASE_URL = "https://www.googleapis.com/youtube/v3"


def _require_api_key():
    if not (API_KEY or "").strip():
        raise ValueError("YOUTUBE_API_KEY is not configured.")

def fetch_channel_videos(channel_id, max_results=25):
    """
    Fetch videos from a YouTube channel
    """
    _require_api_key()
    videos = []
    page_token = None

    while True:
        params = {
            "part": "snippet",
            "channelId": channel_id,
            "maxResults": max_results,
            "order": "date",
            "type": "video",
            "key": API_KEY,
            "pageToken": page_token,
        }

        resp = requests.get(f"{BASE_URL}/search", params=params)
        resp.raise_for_status()

        data = resp.json()

        for item in data.get("items", []):
            videos.append({
                "platform": "youtube",
                "video_id": item["id"]["videoId"],
                "title": item["snippet"]["title"],
                "description": item["snippet"]["description"],
                "published_at": item["snippet"]["publishedAt"],
                "channel_title": item["snippet"]["channelTitle"],
                "scraped_at": datetime.utcnow().isoformat(),
            })

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return videos

def fetch_video_comments(video_id, max_pages=5):
    _require_api_key()
    comments = []
    page_token = None

    for _ in range(max_pages):
        params = {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": 100,
            "textFormat": "plainText",
            "key": API_KEY,
            "pageToken": page_token,
        }

        resp = requests.get(f"{BASE_URL}/commentThreads", params=params)
        if resp.status_code != 200:
            break

        data = resp.json()

        for item in data.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]

            comments.append({
                "video_id": video_id,
                "author": top.get("authorDisplayName"),
                "text": top.get("textDisplay"),
                "likes": top.get("likeCount"),
                "published_at": top.get("publishedAt"),
                "updated_at": top.get("updatedAt"),
            })

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return comments

def fetch_video_stats(video_ids):
    _require_api_key()
    stats = {}

    for i in range(0, len(video_ids), 50):
        params = {
            "part": "statistics",
            "id": ",".join(video_ids[i:i+50]),
            "key": API_KEY,
        }

        resp = requests.get(f"{BASE_URL}/videos", params=params)
        resp.raise_for_status()

        for item in resp.json().get("items", []):
            stats[item["id"]] = item["statistics"]

    return stats

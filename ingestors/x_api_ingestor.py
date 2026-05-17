import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

BEARER = os.getenv("X_BEARER_TOKEN")
BASE_URL = "https://api.twitter.com/2"

HEADERS = {
    "Authorization": f"Bearer {BEARER}"
}

def fetch_user_tweets(username, max_results=10, source_type="official"):
    # 1️⃣ Get user ID
    user_resp = requests.get(
        f"{BASE_URL}/users/by/username/{username}",
        headers=HEADERS
    )
    user_resp.raise_for_status()
    user_id = user_resp.json()["data"]["id"]

    # 2️⃣ Get tweets
    params = {
        "max_results": max_results,
        "tweet.fields": "created_at,public_metrics"
    }

    tweet_resp = requests.get(
        f"{BASE_URL}/users/{user_id}/tweets",
        headers=HEADERS,
        params=params
    )
    tweet_resp.raise_for_status()

    tweets = []
    for t in tweet_resp.json().get("data", []):
        tweets.append({
            "platform": "x",
            "username": username,
            "post_id": t["id"],
            "url": f"https://x.com/{username}/status/{t['id']}",
            "content": t["text"],
            "likes": t["public_metrics"]["like_count"],
            "comments": t["public_metrics"]["reply_count"],
            "shares": t["public_metrics"]["retweet_count"],
            "views": None,
            "timestamp": t["created_at"],
            "scraped_at": datetime.utcnow().isoformat(),
            "source_type": source_type
        })

    return tweets
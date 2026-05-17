import json
from pathlib import Path

DATA_DIR = Path("data/posts")

def load_all_posts():
    posts = []
    for file in DATA_DIR.glob("*.json"):
        with open(file, encoding="utf-8") as f:
            posts.extend(json.load(f))
    return posts

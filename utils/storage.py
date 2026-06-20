import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

# =====================================================
# Base directory
# =====================================================
DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# =====================================================
# Helpers
# =====================================================
def _ensure_platform_dir(platform: str) -> Path:
    """
    Ensure platform directory exists: data/{platform}/
    """
    platform_dir = DATA_DIR / platform
    platform_dir.mkdir(parents=True, exist_ok=True)
    return platform_dir


def _default_filename(username: str, date: Optional[str] = None) -> str:
    """
    Default filename format:
    username_YYYY-MM-DD.json
    """
    date_str = date or str(datetime.utcnow().date())
    return f"{username}_{date_str}.json"


# =====================================================
# Unified Save Function (RECOMMENDED)
# =====================================================
def save_posts(
    posts: List[Dict],
    username: str,
    platform: str,
    date: Optional[str] = None,
    filename: Optional[str] = None
) -> Path:
    """
    Save posts using platform-first layout.

    Args:
        posts: List of normalized post dicts
        username: Account username
        platform: Platform name (instagram, x, youtube, etc.)
        date: Optional date override (YYYY-MM-DD)
        filename: Optional custom filename

    Returns:
        Path to saved file
    """
    platform_dir = _ensure_platform_dir(platform)

    file = platform_dir / (filename or _default_filename(username, date))

    file.write_text(
        json.dumps(posts, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    return file


# =====================================================
# Convenience Wrappers (Optional but Useful)
# =====================================================
def save_instagram_posts(username: str, posts: List[Dict], date: Optional[str] = None) -> Path:
    return save_posts(
        posts=posts,
        username=username,
        platform="instagram",
        date=date
    )


def save_x_posts(username: str, posts: List[Dict], date: Optional[str] = None) -> Path:
    return save_posts(
        posts=posts,
        username=username,
        platform="x",
        date=date
    )


# =====================================================
# Loaders (For Dashboards & Analytics)
# =====================================================
def load_posts(
    platform: Optional[str] = None,
    username: Optional[str] = None
) -> List[Dict]:
    """
    Load posts from disk.

    Args:
        platform: If provided, load only from data/{platform}/
        username: If provided, load only files starting with username_

    Returns:
        List of post dicts
    """
    base_dir = DATA_DIR / platform if platform else DATA_DIR

    if not base_dir.exists():
        return []

    all_posts = []

    pattern = f"{username}_*.json" if username else "*.json"

    for file in base_dir.rglob(pattern):
        try:
            with open(file, encoding="utf-8") as f:
                all_posts.extend(json.load(f))
        except Exception:
            continue

    return all_posts

def load_existing_x_post_ids(username: str) -> set[str]:
    """
    Load all existing X post IDs for a username
    """
    data_dir = Path("data/x")
    ids = set()

    for file in data_dir.glob(f"{username}_*.json"):
        try:
            with open(file, encoding="utf-8") as f:
                posts = json.load(f)
                for p in posts:
                    if "post_id" in p:
                        ids.add(p["post_id"])
        except Exception:
            continue

    return ids


def save_youtube_videos(channel_name, videos):
    path = Path("data/youtube/channel_videos")
    path.mkdir(parents=True, exist_ok=True)

    file = path / f"{channel_name}_{datetime.utcnow().date()}.json"
    file.write_text(json.dumps(videos, indent=2, ensure_ascii=False))
    return file


def save_youtube_comments(video_id, comments):
    path = Path("data/youtube/video_comments")
    path.mkdir(parents=True, exist_ok=True)

    file = path / f"{video_id}_{datetime.utcnow().date()}.json"
    file.write_text(json.dumps(comments, indent=2, ensure_ascii=False))
    return file
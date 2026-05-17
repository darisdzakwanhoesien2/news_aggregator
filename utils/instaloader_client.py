from datetime import datetime
from urllib.parse import urlparse

import instaloader


class InstagramScraperError(Exception):
    """Raised when Instagram scraping fails in a recoverable way."""


def normalize_instagram_username(username: str) -> str:
    cleaned = (username or "").strip()
    if not cleaned:
        raise InstagramScraperError("Please enter a valid Instagram username.")

    if "instagram.com" in cleaned:
        parsed = urlparse(cleaned)
        path_parts = [part for part in parsed.path.split("/") if part]
        cleaned = path_parts[0] if path_parts else ""

    cleaned = cleaned.lstrip("@").strip().strip("/")

    if not cleaned:
        raise InstagramScraperError("Please enter a valid Instagram username.")

    return cleaned


def fetch_instagram_posts(username, max_posts=20):
    normalized_username = normalize_instagram_username(username)
    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_comments=False,
        save_metadata=False,
        quiet=True
    )

    try:
        profile = instaloader.Profile.from_username(L.context, normalized_username)
    except instaloader.exceptions.ProfileNotExistsException as exc:
        raise InstagramScraperError(
            f"Instagram profile '{normalized_username}' does not exist."
        ) from exc
    except instaloader.exceptions.TooManyRequestsException as exc:
        raise InstagramScraperError(
            "Instagram rate-limited the request. Please try again later."
        ) from exc
    except instaloader.exceptions.LoginRequiredException as exc:
        raise InstagramScraperError(
            "Instagram requires login for this profile. Try the Playwright fallback."
        ) from exc
    except (
        instaloader.exceptions.BadResponseException,
        instaloader.exceptions.ConnectionException,
        instaloader.exceptions.QueryReturnedBadRequestException,
    ) as exc:
        raise InstagramScraperError(
            "Instagram request failed. Please try again in a moment."
        ) from exc

    posts = []
    try:
        for i, post in enumerate(profile.get_posts()):
            if i >= max_posts:
                break

            posts.append({
                "username": normalized_username,
                "shortcode": post.shortcode,
                "url": f"https://www.instagram.com/p/{post.shortcode}/",
                "caption": post.caption,
                "likes": post.likes,
                "comments": post.comments,
                "timestamp": post.date_utc.isoformat(),
                "scraped_at": datetime.utcnow().isoformat()
            })
    except instaloader.exceptions.PrivateProfileNotFollowedException as exc:
        raise InstagramScraperError(
            f"Instagram profile '{normalized_username}' is private."
        ) from exc
    except instaloader.exceptions.LoginRequiredException as exc:
        raise InstagramScraperError(
            "Instagram requires login to read posts from this profile."
        ) from exc

    return posts

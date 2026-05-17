import instaloader
from datetime import datetime

def fetch_instagram_posts(username, max_posts=20):
    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_comments=False,
        save_metadata=False,
        quiet=True
    )

    profile = instaloader.Profile.from_username(L.context, username)

    posts = []
    for i, post in enumerate(profile.get_posts()):
        if i >= max_posts:
            break

        posts.append({
            "username": username,
            "shortcode": post.shortcode,
            "url": f"https://www.instagram.com/p/{post.shortcode}/",
            "caption": post.caption,
            "likes": post.likes,
            "comments": post.comments,
            "timestamp": post.date_utc.isoformat(),
            "scraped_at": datetime.utcnow().isoformat()
        })

    return posts
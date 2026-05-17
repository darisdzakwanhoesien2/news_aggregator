import streamlit as st
import pandas as pd
import re

from ingestors.youtube_api_ingestor import (
    fetch_channel_videos,
    fetch_video_stats,
    fetch_video_comments,
)
from utils.storage import (
    save_youtube_videos,
    save_youtube_comments,
)
from utils.youtube_utils import get_channel_id_from_url

# =====================================================
# Page config
# =====================================================
st.set_page_config(
    page_title="📺 YouTube ESG Scraper",
    layout="wide"
)

st.title("📺 YouTube ESG Scraper")
st.markdown("""
Scrape **YouTube channels or individual videos** for ESG analysis.

Supports:
- Channel ID
- Channel URL (`@handle`)
- Single video URL
""")

# =====================================================
# Mode selector
# =====================================================
mode = st.radio(
    "Scrape Mode",
    ["Channel", "Single Video"]
)

# =====================================================
# Common options
# =====================================================
fetch_comments = st.checkbox(
    "Fetch comments",
    value=True
)

max_comment_pages = st.slider(
    "Max comment pages per video (100 comments/page)",
    min_value=1,
    max_value=10,
    value=3
)

# =====================================================
# CHANNEL MODE
# =====================================================
if mode == "Channel":
    st.subheader("📂 Channel Scraping")

    channel_input = st.text_input(
        "YouTube Channel ID or URL",
        placeholder="https://www.youtube.com/@PTPertamina"
    )

    channel_name = st.text_input(
        "Channel Name (for storage)",
        placeholder="pertamina"
    )

    max_videos = st.slider(
        "Max videos to fetch",
        min_value=5,
        max_value=50,
        value=10
    )

# =====================================================
# VIDEO MODE
# =====================================================
else:
    st.subheader("🎬 Single Video Scraping")

    video_url = st.text_input(
        "YouTube Video URL",
        placeholder="https://www.youtube.com/watch?v=VIDEO_ID"
    )

    channel_name = st.text_input(
        "Channel Name (for storage)",
        placeholder="pertamina"
    )

# =====================================================
# Helper: extract video ID
# =====================================================
def extract_video_id(url: str) -> str | None:
    match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
    return match.group(1) if match else None

# =====================================================
# Action
# =====================================================
if st.button("🚀 Scrape YouTube"):
    if not channel_name:
        st.warning("Please provide a Channel Name for storage.")
        st.stop()

    # =================================================
    # CHANNEL MODE LOGIC
    # =================================================
    if mode == "Channel":
        if not channel_input:
            st.warning("Please provide a Channel ID or URL.")
            st.stop()

        # Resolve channel ID
        if channel_input.startswith("http"):
            channel_id = get_channel_id_from_url(channel_input)
            if not channel_id:
                st.error("Could not resolve Channel ID from URL.")
                st.stop()
        else:
            channel_id = channel_input

        with st.spinner("Fetching channel videos…"):
            videos = fetch_channel_videos(
                channel_id=channel_id,
                max_results=max_videos
            )

        if not videos:
            st.error("No videos found.")
            st.stop()

        video_df = pd.DataFrame(videos)

    # =================================================
    # SINGLE VIDEO MODE LOGIC
    # =================================================
    else:
        video_id = extract_video_id(video_url or "")
        if not video_id:
            st.error("Invalid YouTube video URL.")
            st.stop()

        video_df = pd.DataFrame([{
            "platform": "youtube",
            "video_id": video_id,
            "title": None,
            "description": None,
            "published_at": None,
            "scraped_at": pd.Timestamp.utcnow().isoformat()
        }])

    # =================================================
    # Fetch stats
    # =================================================
    with st.spinner("Fetching video statistics…"):
        stats = fetch_video_stats(video_df["video_id"].tolist())

    for i, row in video_df.iterrows():
        s = stats.get(row["video_id"], {})
        video_df.loc[i, "views"] = s.get("viewCount")
        video_df.loc[i, "likes"] = s.get("likeCount")
        video_df.loc[i, "comments"] = s.get("commentCount")

    st.success(f"✅ Fetched {len(video_df)} video(s)")

    # =================================================
    # Preview videos
    # =================================================
    st.subheader("🎬 Video Preview")

    st.dataframe(
        video_df[
            ["video_id", "title", "published_at", "views", "likes", "comments"]
        ],
        use_container_width=True
    )

    # =================================================
    # Save videos
    # =================================================
    video_path = save_youtube_videos(
        channel_name,
        video_df.to_dict("records")
    )
    st.info(f"💾 Videos saved to `{video_path}`")

    # =================================================
    # Fetch comments
    # =================================================
    if fetch_comments:
        all_comments = []

        with st.spinner("Fetching video comments…"):
            for _, row in video_df.iterrows():
                comments = fetch_video_comments(
                    video_id=row["video_id"],
                    max_pages=max_comment_pages
                )
                all_comments.extend(comments)

        if all_comments:
            comment_df = pd.DataFrame(all_comments)

            st.subheader("💬 Comments Preview")
            st.dataframe(
                comment_df[
                    ["video_id", "author", "text", "likes", "published_at"]
                ],
                use_container_width=True
            )

            for video_id, group in comment_df.groupby("video_id"):
                save_youtube_comments(
                    video_id,
                    group.to_dict("records")
                )

            st.success(f"✅ Saved {len(comment_df)} comments")

        else:
            st.warning("No comments retrieved.")

    # =================================================
    # Download
    # =================================================
    st.download_button(
        "⬇️ Download Videos JSON",
        video_df.to_json(orient="records", indent=2),
        file_name=f"youtube_{channel_name}_videos.json"
    )


# import streamlit as st
# import pandas as pd

# from ingestors.youtube_api_ingestor import (
#     fetch_channel_videos,
#     fetch_video_stats,
#     fetch_video_comments,
# )
# from utils.storage import (
#     save_youtube_videos,
#     save_youtube_comments,
# )

# # =====================================================
# # Page config
# # =====================================================
# st.set_page_config(
#     page_title="📺 YouTube ESG Scraper",
#     layout="wide"
# )

# st.title("📺 YouTube ESG Scraper")
# st.markdown("""
# Scrape **YouTube channels** for ESG analysis:

# - Video titles & descriptions
# - Engagement statistics
# - Public comments (sentiment & controversy signals)

# Powered by **YouTube Data API v3**
# """)

# # =====================================================
# # Inputs
# # =====================================================
# channel_id = st.text_input(
#     "YouTube Channel ID",
#     placeholder="UC_x5XG1OV2P6uZZ5FSM9Ttw"
# )

# channel_name = st.text_input(
#     "Channel Name (for storage)",
#     placeholder="pertamina"
# )

# max_videos = st.slider(
#     "Max videos to fetch",
#     min_value=5,
#     max_value=50,
#     value=10
# )

# fetch_comments = st.checkbox(
#     "Fetch comments for each video",
#     value=True
# )

# max_comment_pages = st.slider(
#     "Max comment pages per video (100 comments/page)",
#     min_value=1,
#     max_value=10,
#     value=3
# )

# # =====================================================
# # Action
# # =====================================================
# if st.button("🚀 Scrape YouTube"):
#     if not channel_id or not channel_name:
#         st.warning("Please provide both Channel ID and Channel Name.")
#         st.stop()

#     with st.spinner("Fetching videos from YouTube…"):
#         videos = fetch_channel_videos(
#             channel_id=channel_id,
#             max_results=max_videos
#         )

#     if not videos:
#         st.error("No videos found.")
#         st.stop()

#     video_df = pd.DataFrame(videos)

#     # =================================================
#     # Fetch stats
#     # =================================================
#     with st.spinner("Fetching video statistics…"):
#         stats = fetch_video_stats(video_df["video_id"].tolist())

#     for i, row in video_df.iterrows():
#         s = stats.get(row["video_id"], {})
#         video_df.loc[i, "views"] = s.get("viewCount")
#         video_df.loc[i, "likes"] = s.get("likeCount")
#         video_df.loc[i, "comments"] = s.get("commentCount")

#     st.success(f"✅ Fetched {len(video_df)} videos")

#     # =================================================
#     # Preview videos
#     # =================================================
#     st.subheader("🎬 Videos Preview")

#     st.dataframe(
#         video_df[
#             [
#                 "video_id",
#                 "title",
#                 "published_at",
#                 "views",
#                 "likes",
#                 "comments",
#             ]
#         ],
#         use_container_width=True
#     )

#     # =================================================
#     # Save videos
#     # =================================================
#     video_path = save_youtube_videos(channel_name, video_df.to_dict("records"))
#     st.info(f"💾 Videos saved to `{video_path}`")

#     # =================================================
#     # Fetch comments
#     # =================================================
#     if fetch_comments:
#         all_comments = []

#         with st.spinner("Fetching video comments…"):
#             for _, row in video_df.iterrows():
#                 comments = fetch_video_comments(
#                     video_id=row["video_id"],
#                     max_pages=max_comment_pages
#                 )
#                 all_comments.extend(comments)

#         if all_comments:
#             comment_df = pd.DataFrame(all_comments)

#             st.subheader("💬 Comments Preview")
#             st.dataframe(
#                 comment_df[
#                     ["video_id", "author", "text", "likes", "published_at"]
#                 ],
#                 use_container_width=True
#             )

#             # Save comments per video
#             for video_id, group in comment_df.groupby("video_id"):
#                 save_youtube_comments(
#                     video_id,
#                     group.to_dict("records")
#                 )

#             st.success(f"✅ Saved {len(comment_df)} comments")

#         else:
#             st.warning("No comments retrieved (disabled or limited).")

#     # =================================================
#     # Download
#     # =================================================
#     st.download_button(
#         "⬇️ Download Videos JSON",
#         video_df.to_json(orient="records", indent=2, ensure_ascii=False),
#         file_name=f"youtube_{channel_name}_videos.json"
#     )

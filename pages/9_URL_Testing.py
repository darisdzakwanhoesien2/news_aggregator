import streamlit as st
from utils.youtube_utils import get_channel_id_from_url

yt_url = st.text_input(
    "YouTube Channel URL",
    placeholder="https://www.youtube.com/@PTPertamina"
)

if yt_url:
    channel_id = get_channel_id_from_url(yt_url)
    if channel_id:
        st.success(f"Channel ID: {channel_id}")
    else:
        st.error("Could not resolve Channel ID")

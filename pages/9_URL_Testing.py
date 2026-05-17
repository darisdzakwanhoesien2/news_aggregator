import streamlit as st
from utils.youtube_utils import get_channel_id_from_url
from _page_descriptions import render_page_description

st.set_page_config(page_title="YouTube URL Tester", layout="wide")
st.title("🔗 YouTube URL Tester")
render_page_description(__file__)

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

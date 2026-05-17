import streamlit as st

from _page_descriptions import render_page_description


st.set_page_config(page_title="Research Map", layout="wide")
st.title("Research Map")
render_page_description(__file__)

st.info(
    "This page is currently a placeholder for a future experiment index or "
    "research-navigation dashboard."
)

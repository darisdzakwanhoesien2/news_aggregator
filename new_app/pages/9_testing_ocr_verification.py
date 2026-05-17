import streamlit as st

from _page_descriptions import render_page_description


st.set_page_config(page_title="OCR Verification Testing", layout="wide")
st.title("OCR Verification Testing")
render_page_description(__file__)

st.info(
    "This page is reserved for OCR verification experiments and currently acts "
    "as a lightweight placeholder."
)

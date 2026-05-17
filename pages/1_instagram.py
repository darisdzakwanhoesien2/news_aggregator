import streamlit as st

st.set_page_config(layout="wide")
st.title("📸 Instagram Scraper")

st.warning(
    "Instagram scraping requires the official Meta Graph API.\n\n"
    "Direct scraping is not supported due to ToS restrictions."
)

st.markdown("""
**Recommended approach:**
1. Use Meta Graph API
2. Connect business account
3. Fetch posts & comments via API
""")

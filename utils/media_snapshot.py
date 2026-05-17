from pathlib import Path
import streamlit as st

MEDIA_DIR = Path("data/media")

def render_snapshot(post):
    st.markdown("### 🧾 Archived Post Snapshot")

    company_dir = MEDIA_DIR / post["username"]
    image_path = company_dir / f"{post['shortcode']}.jpg"

    if image_path.exists():
        st.image(str(image_path), use_container_width=True)
    else:
        st.info("No archived image available.")

    st.markdown("**Caption**")
    st.write(post["caption"])

    col1, col2 = st.columns(2)
    col1.metric("Likes", post["likes"])
    col2.metric("Comments", post["comments"])

    st.link_button("🔗 Open on Instagram", post["url"])

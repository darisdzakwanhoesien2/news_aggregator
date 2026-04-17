import streamlit as st


def get_query_params() -> dict:
    """Return query params in the legacy dict-of-lists shape."""
    if hasattr(st, "query_params"):
        params = st.query_params
        return {key: [value] if isinstance(value, str) else list(value) for key, value in params.items()}
    if hasattr(st, "experimental_get_query_params"):
        return st.experimental_get_query_params()
    return {}


def set_query_params(**params) -> None:
    """Set query params using whichever Streamlit API is available."""
    if hasattr(st, "query_params"):
        st.query_params.clear()
        for key, value in params.items():
            if value is None:
                continue
            st.query_params[key] = value
        return
    if hasattr(st, "experimental_set_query_params"):
        st.experimental_set_query_params(**params)

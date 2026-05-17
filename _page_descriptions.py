from pathlib import Path


def render_page_description(page_file: str) -> None:
    page_path = Path(page_file).resolve()
    parts = page_path.parts

    if "public_account" in parts and "pages" in parts:
        from public_account.pages._page_descriptions import render_page_description as _render
    elif "new_app" in parts and "pages" in parts:
        from new_app.pages._page_descriptions import render_page_description as _render
    else:
        from pages._page_descriptions import render_page_description as _render

    _render(page_file)

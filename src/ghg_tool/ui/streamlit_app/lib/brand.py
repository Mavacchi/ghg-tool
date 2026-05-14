"""Brand-chrome helpers — logo + CSS injection applied on every page.

In Streamlit's multipage routing each page re-runs its own script,
so brand-level UI (the top-left logo, the sidebar logo, the CSS
polish layer) is not inherited from ``Home.py``. We centralise the
setup in ``apply_brand_chrome()`` so every page module can opt in
with a single call right after ``require_auth``.

Falls back gracefully when the bundled assets are missing (e.g.
partial checkout / smoke tests): the helper simply skips the
visual touch-ups so the dashboard still launches.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Final

import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    COMPANY_SHORT,
    FAVICON_PATH,
    LOGO_PATH,
    PRODUCT_NAME,
)

_BRAND_CSS_PATH: Final[Path] = (
    Path(__file__).parent.parent / "assets" / "brand.css"
)


@lru_cache(maxsize=1)
def _brand_css() -> str:
    """Read the brand-chrome stylesheet once per process.

    Returns an empty string if the file is missing so injection is a no-op.
    """
    try:
        return _BRAND_CSS_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _inject_css() -> None:
    """Inject the brand-chrome stylesheet into the current page.

    The ``<style>`` block is wrapped in ``unsafe_allow_html=True``; the
    content comes from a project asset, never from user input.
    """
    css = _brand_css()
    if css:
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _register_top_logo() -> None:
    """Wire ``st.logo()`` so the brand logo appears in the top-left
    header bar and (collapsed) at the top-left when the sidebar is hidden.

    Safe across Streamlit versions: ``st.logo`` was added in 1.35; older
    versions silently skip this branch.
    """
    if not (hasattr(st, "logo") and LOGO_PATH.exists()):
        return
    icon = str(FAVICON_PATH) if FAVICON_PATH.exists() else None
    st.logo(str(LOGO_PATH), icon_image=icon)


def _render_sidebar_logo() -> None:
    """Render a larger logo block at the very top of the sidebar.

    ``st.logo()`` gives a compact wordmark in the top-left chrome; this
    helper adds a more prominent logo inside the sidebar itself, scoped
    by the ``.brand-sidebar-logo`` CSS class so width / spacing are
    controlled centrally in ``assets/brand.css``.
    """
    if not LOGO_PATH.exists():
        return
    # base64-embedded so the asset travels with the HTML and works even
    # when Streamlit's static-files server is namespaced behind a reverse
    # proxy that rewrites URLs.
    import base64  # noqa: PLC0415

    data = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    st.sidebar.markdown(
        f'<div class="brand-sidebar-logo">'
        f'<img src="data:image/png;base64,{data}" '
        f'alt="{COMPANY_SHORT} — {PRODUCT_NAME}">'
        f"</div>",
        unsafe_allow_html=True,
    )


def apply_brand_chrome() -> None:
    """One-call brand setup. Call near the top of every page script.

    Composition:
      1. ``st.logo()`` — top-left header logo + collapsed sidebar icon.
      2. CSS polish layer — typography, metric cards, sidebar rhythm.
      3. Sidebar logo block — large wordmark anchored at the top of
         the sidebar so the brand reads on every page, not just Home.
    """
    _register_top_logo()
    _inject_css()
    _render_sidebar_logo()

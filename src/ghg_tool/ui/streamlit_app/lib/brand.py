"""Brand-chrome helpers - logo + CSS injection applied on every page.

In Streamlit's multipage routing each page re-runs its own script,
so brand-level UI (the logo at the top of the sidebar, the CSS polish
layer) is not inherited from ``Home.py``. We centralise the setup in
``apply_brand_chrome()`` so every page module can opt in with a single
call right after ``require_auth``.

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
    FAVICON_PATH,
    LOGO_COLLAPSED_PATH,
    LOGO_PATH,
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


def _register_logo() -> None:
    """Wire ``st.logo()`` so the brand logo appears in the top-left of
    the sidebar, with the reduced wordmark shown when the sidebar is
    collapsed.

    Asset precedence for ``icon_image`` (the collapsed-sidebar variant):
    the reduced Gresmalt wordmark when available, otherwise the favicon,
    otherwise nothing. ``st.logo`` was added in Streamlit 1.35; older
    versions silently skip this branch.
    """
    if not (hasattr(st, "logo") and LOGO_PATH.exists()):
        return
    if LOGO_COLLAPSED_PATH.exists():
        icon = str(LOGO_COLLAPSED_PATH)
    elif FAVICON_PATH.exists():
        icon = str(FAVICON_PATH)
    else:
        icon = None
    st.logo(str(LOGO_PATH), icon_image=icon)


def apply_brand_chrome() -> None:
    """One-call brand setup. Call near the top of every page script.

    Composition:
      1. ``st.logo()`` - the only logo on the page (top of sidebar when
         expanded, top-left header when collapsed). One logo, not two.
      2. CSS polish layer - typography, metric cards, sidebar rhythm,
         logo sizing, motion.
    """
    _register_logo()
    _inject_css()


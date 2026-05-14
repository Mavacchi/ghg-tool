"""Brand-chrome helpers - logo + CSS injection applied on every page.

In Streamlit's multipage routing each page re-runs its own script,
so brand-level UI (the logo at the top of the sidebar, the CSS polish
layer) is not inherited from ``Home.py``. We centralise the setup in
``apply_brand_chrome()`` so every page module can opt in with a single
call right after ``require_auth``.

The helper also renders accessibility scaffolding (skip-link) and an
optional sticky context bar that shows the user's active year / GWP /
role so navigation never strips that context away.

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


def _render_skip_link(lang: str) -> None:
    """Render an accessibility skip-link that becomes visible on tab focus.

    Lets keyboard / screen-reader users bypass the brand chrome and
    jump straight to the main content. Anchors to the implicit
    ``[data-testid="stMain"]`` element via ``#main`` — Streamlit does
    not add that id by default, so the anchor is informational; the
    main affordance is putting the focus far enough down the tab order.
    """
    label = "Salta al contenuto" if lang == "it" else "Skip to main content"
    st.markdown(
        f'<a href="#main" class="ct-skip-link">{label}</a>',
        unsafe_allow_html=True,
    )


def render_context_bar(
    *,
    lang: str,
    year: int | None = None,
    gwp: str | None = None,
    role: str | None = None,
) -> None:
    """Render a sticky one-line context strip below the toolbar.

    Shows whichever of ``year`` / ``gwp`` / ``role`` are supplied. The
    bar sticks to the top of the viewport via ``position: sticky``
    (see ``.ct-sticky-context`` in ``brand.css``) so the user always
    knows what filter context they're operating under.

    Args:
        lang: Active language code (for IT/EN labels).
        year: Reporting year, e.g. 2025. Omit to hide.
        gwp: GWP set string, e.g. "AR6". Omit to hide.
        role: Active user role, e.g. "esg_manager". Omit to hide.
    """
    parts: list[str] = []
    if year is not None:
        label = "Anno" if lang == "it" else "Year"
        parts.append(
            f'<span><span class="ct-ctx-key">{label}</span>'
            f'<span class="ct-ctx-val">{year}</span></span>'
        )
    if gwp:
        label = "GWP" if lang == "it" else "GWP"
        parts.append(
            f'<span><span class="ct-ctx-key">{label}</span>'
            f'<span class="ct-ctx-val">{gwp}</span></span>'
        )
    if role:
        label = "Ruolo" if lang == "it" else "Role"
        parts.append(
            f'<span><span class="ct-ctx-key">{label}</span>'
            f'<span class="ct-ctx-val">{role}</span></span>'
        )
    if not parts:
        return
    sep = '<span class="ct-ctx-sep" aria-hidden="true">|</span>'
    inner = sep.join(parts)
    st.markdown(
        f'<div class="ct-sticky-context" role="status" aria-live="polite">'
        f"{inner}</div>",
        unsafe_allow_html=True,
    )


def apply_brand_chrome(lang: str | None = None) -> None:
    """One-call brand setup. Call near the top of every page script.

    Composition:
      1. ``st.logo()`` - the only logo on the page (top of sidebar when
         expanded, top-left header when collapsed). One logo, not two.
      2. CSS polish layer - typography, metric cards, sidebar rhythm,
         logo sizing, motion, mobile breakpoints, accessibility focus
         rings.
      3. Skip-link for keyboard / screen-reader users (only visible
         when focused).

    Args:
        lang: Optional language code. When omitted the helper reads
            ``st.session_state['lang']`` (set by Home.py's sidebar
            selector) and falls back to IT if absent.
    """
    if lang is None:
        # Deferred import keeps lib.brand a leaf module at import time.
        lang = st.session_state.get("lang", "it")
    _register_logo()
    _inject_css()
    _render_skip_link(lang)


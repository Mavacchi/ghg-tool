"""Shared filter widgets backed by st.session_state.

Streamlit re-runs each page script on every interaction, but
``st.session_state`` survives across reruns and across page changes.
Storing the active filter values under stable keys (``g_year``, ``g_gwp``)
gives the user a consistent context: changing the year on the Home page
and then navigating to Drill-down keeps the same year in the sidebar
without re-fetching defaults.

Pages call:

    from ghg_tool.ui.streamlit_app.lib.filters import (
        sidebar_year_filter, sidebar_gwp_filter,
    )

    with st.sidebar:
        selected_year = sidebar_year_filter(lang)
        selected_gwp  = sidebar_gwp_filter(lang)

The helpers also expose ``current_year()`` / ``current_gwp()`` getters
for pages that need the value WITHOUT rendering a widget (e.g. for the
sidebar of the YoY page, which has its own dual-year widgets).
"""

from __future__ import annotations

import datetime as _dt
from typing import Final

import streamlit as st

from ghg_tool.ui.streamlit_app.lib.help import _help
from ghg_tool.ui.streamlit_app.lib.i18n import _

# Session-state keys (stable across pages).
_YEAR_KEY: Final[str] = "g_year"
_GWP_KEY: Final[str] = "g_gwp"

_YEAR_OPTIONS: Final[list[int]] = list(range(2024, 2027))
_GWP_OPTIONS: Final[list[str]] = ["AR6", "AR5"]


def _default_year() -> int:
    """Return the year shown the first time the user lands on a page."""
    current = _dt.date.today().year
    return current if current in _YEAR_OPTIONS else _YEAR_OPTIONS[-1]


def current_year() -> int:
    """Return the active reporting year from session state (or default)."""
    val = st.session_state.get(_YEAR_KEY)
    if isinstance(val, int) and val in _YEAR_OPTIONS:
        return val
    return _default_year()


def current_gwp() -> str:
    """Return the active GWP set from session state (or default)."""
    val = st.session_state.get(_GWP_KEY)
    if isinstance(val, str) and val in _GWP_OPTIONS:
        return val
    return _GWP_OPTIONS[0]


def sidebar_year_filter(lang: str = "it") -> int:
    """Render the fiscal-year selectbox in the sidebar and return the value.

    The widget reads from and writes to ``st.session_state[g_year]`` via
    Streamlit's ``key=`` mechanism, so the choice survives navigation.
    """
    # Seed the session-state entry on first access so the selectbox
    # honours the default without flickering.
    if _YEAR_KEY not in st.session_state:
        st.session_state[_YEAR_KEY] = _default_year()
    return st.selectbox(
        _("year_filter", lang),
        _YEAR_OPTIONS,
        key=_YEAR_KEY,
        help=_help("anno_fiscale", lang),
    )


def sidebar_gwp_filter(lang: str = "it") -> str:
    """Render the GWP-set selectbox in the sidebar and return the value."""
    if _GWP_KEY not in st.session_state:
        st.session_state[_GWP_KEY] = _GWP_OPTIONS[0]
    return st.selectbox(
        "GWP Set",
        _GWP_OPTIONS,
        key=_GWP_KEY,
        help=_help("gwp", lang),
    )

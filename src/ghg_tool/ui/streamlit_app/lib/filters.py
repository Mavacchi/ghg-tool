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

# Query-param keys for URL-bookmarkable filter state.
_YEAR_QP: Final[str] = "y"
_GWP_QP: Final[str] = "g"


def _read_query_params_into_state() -> None:
    """Hydrate session state from URL query params on first page load.

    Lets the user bookmark a Drill-down view with a specific year + GWP set:
    visiting ``?y=2025&g=AR6`` puts the dashboard in that state. Idempotent:
    only writes to session state when the value is missing so it never
    overrides an explicit in-app selection.
    """
    try:
        qp = st.query_params
    except AttributeError:  # pragma: no cover - Streamlit < 1.31 fallback
        return
    if _YEAR_KEY not in st.session_state:
        raw_y = qp.get(_YEAR_QP)
        if raw_y:
            try:
                year = int(raw_y)
            except (TypeError, ValueError):
                year = None
            if isinstance(year, int) and year in _YEAR_OPTIONS:
                st.session_state[_YEAR_KEY] = year
    if _GWP_KEY not in st.session_state:
        raw_g = qp.get(_GWP_QP)
        if isinstance(raw_g, str) and raw_g in _GWP_OPTIONS:
            st.session_state[_GWP_KEY] = raw_g


def _sync_query_params_from_state() -> None:
    """Write the active year + GWP back to the URL.

    Triggered after each widget interaction so that copying the URL
    produces a link that restores the same filter state. Skips when
    Streamlit version is too old to expose ``st.query_params``.
    """
    try:
        qp = st.query_params
    except AttributeError:  # pragma: no cover
        return
    year = st.session_state.get(_YEAR_KEY)
    gwp = st.session_state.get(_GWP_KEY)
    if isinstance(year, int):
        qp[_YEAR_QP] = str(year)
    if isinstance(gwp, str):
        qp[_GWP_QP] = gwp


def available_years() -> list[int]:
    """Return the canonical list of selectable fiscal years.

    Pages with year-related UI that does NOT go through the shared
    sidebar widgets (e.g. dual-year YoY, Audit Trail filter) should
    call this getter so the option list stays in one place.
    """
    return list(_YEAR_OPTIONS)


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
    Also synced to / from URL query params so the active filter is
    bookmarkable (?y=2025&g=AR6).
    """
    _read_query_params_into_state()
    if _YEAR_KEY not in st.session_state:
        st.session_state[_YEAR_KEY] = _default_year()
    value = st.selectbox(
        _("year_filter", lang),
        _YEAR_OPTIONS,
        key=_YEAR_KEY,
        help=_help("anno_fiscale", lang),
    )
    _sync_query_params_from_state()
    return value


def sidebar_gwp_filter(lang: str = "it") -> str:
    """Render the GWP-set selectbox in the sidebar and return the value."""
    _read_query_params_into_state()
    if _GWP_KEY not in st.session_state:
        st.session_state[_GWP_KEY] = _GWP_OPTIONS[0]
    value = st.selectbox(
        _("gwp_filter_label", lang),
        _GWP_OPTIONS,
        key=_GWP_KEY,
        help=_help("gwp", lang),
    )
    _sync_query_params_from_state()
    return value

"""VIANO 2025 reduced-operation banner (FR-24, MG-12).

Displays a prominent warning banner when ALL of:
  1. The selected year is 2025, AND
  2. The tenant has site VIANO in scope, AND
  3. We are displaying any aggregate (not an empty/filtered-out view).

Banner text comes from the active translation (IT default).
"""

from __future__ import annotations

import streamlit as st

from ghg_tool.ui.streamlit_app.lib.i18n import _

# Site codes that trigger the VIANO banner
_VIANO_SITE_CODES: frozenset[str] = frozenset({"VIANO", "VIANO_GARGOLA"})

# Year that triggers the banner
_BANNER_YEAR: int = 2025


def should_show_viano_banner(
    selected_year: int,
    visible_sites: list[str] | None = None,
) -> bool:
    """Return True when the VIANO 2025 banner should be displayed.

    Args:
        selected_year: The year currently selected in the UI filter.
        visible_sites: List of site codes currently visible/unfiltered.
            If None, assumes all 7 sites are visible (conservative: show banner).

    Returns:
        True if banner should be shown.
    """
    if selected_year != _BANNER_YEAR:
        return False
    if visible_sites is None:
        return True
    return bool(_VIANO_SITE_CODES & set(visible_sites))


def render_viano_banner(lang: str = "it") -> None:
    """Render the VIANO 2025 reduced-operation banner in the Streamlit UI.

    Uses ``st.warning`` with an explicit icon so the banner is visible
    even when colour perception is impaired (WCAG — no colour-only cue).

    Args:
        lang: Language code for the banner text.
    """
    text = _("viano_banner", lang)
    st.warning(f"AVVISO / WARNING: {text}", icon="⚠️")

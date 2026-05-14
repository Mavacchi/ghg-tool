"""Intensity Metrics page (FR-25, FR-26).

Displays ESRS E1-6 §45 intensity ratios (KPI-09 / KPI-10 / KPI-11) fetched
from ``GET /api/v1/intensity``.

Controls:
  - Denominator selector (4 FR-26 types)
  - Year range slider
  - Site multi-select (optional)
  - GWP set selector

Visualisations:
  - Plotly line chart (one series per scope_label)
  - Tabular view with CSV download
  - Provenance tooltips (factor_source, factor_version, gwp_set, methodology)
  - VIANO 2025 banner when applicable
"""

from __future__ import annotations

import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    DASHBOARD_ID, DASHBOARD_VERSION, PRODUCT_NAME, page_icon,
)

st.set_page_config(
    page_title=f"Intensity Metrics · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

import datetime as dt  # noqa: E402

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402

from ghg_tool.ui.streamlit_app.lib.api_client import fetch_intensity  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.banner import render_viano_banner, should_show_viano_banner  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.brand import apply_brand_chrome, render_context_bar  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.filters import sidebar_gwp_filter  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.help import _help  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.palette import (  # noqa: E402
    BLUE,
    BLUISH_GREEN,
    ORANGE,
    VERMILION,
)
from ghg_tool.ui.streamlit_app.lib.tooltips import build_emission_hovertemplate  # noqa: E402

apply_brand_chrome()
require_auth()
lang = get_lang()

st.title(_("nav_intensity", lang))

# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------

# Denominator type → API value mapping (FR-26)
_DENOM_LABELS: dict[str, str] = {
    _("intensity_eur_revenue", lang): "EUR_revenue",
    _("intensity_m2_production", lang): "m2_production",
    _("intensity_fte", lang): "FTE",
    _("intensity_kg_product", lang): "kg_product",
}

_DENOM_UNIT_LABEL: dict[str, str] = {
    "EUR_revenue": "tCO2e / EUR",
    "m2_production": "tCO2e / m²",
    "FTE": "tCO2e / FTE",
    "kg_product": "tCO2e / kg",
}

_CURRENT_YEAR: int = dt.date.today().year  # REV-WAVE3-009: derived dynamically

_DENOM_HELP_KEYS: dict[str, str] = {
    "EUR_revenue": "intensity_revenue",
    "m2_production": "intensity_m2",
    "FTE": "intensity_fte",
    "kg_product": "intensity_kg_product",
}

with st.sidebar:
    gwp_set = sidebar_gwp_filter(lang)

    denom_label = st.selectbox(
        _("intensity_denominator", lang),
        list(_DENOM_LABELS.keys()),
        key="intensity_denom",
        help=_help("intensity_revenue", lang),
    )
    denominator_type = _DENOM_LABELS[denom_label]  # type: ignore[index]

    year_range = st.slider(
        "Anno (da / a)",
        min_value=2020,
        max_value=_CURRENT_YEAR,
        value=(_CURRENT_YEAR - 4, _CURRENT_YEAR),
        key="intensity_years",
    )
    anno_from, anno_to = year_range

    # Known sites — kept in sync with requirements.md §5.2
    _ALL_SITES: list[str] = [
        "IANO", "VIANO", "VIANO_GARGOLA",
        "CASALGRANDE", "FIORANO", "SASSUOLO", "FRASSINORO",
    ]
    selected_sites: list[str] = st.multiselect(
        _("sites_filter_hint", lang),
        _ALL_SITES,
        default=[],
        key="intensity_sites",
    )

# ---------------------------------------------------------------------------
# Fetch data from API
# ---------------------------------------------------------------------------

# SEC-P0-003: tenant_id is no longer passed to fetch_intensity.
# The backend sources tenant isolation exclusively from the JWT claim.
# When site filter is used, fetch per-site (first site only in single-select mode).
# For multi-site aggregate, pass codice_sito=None.
fetch_site: str | None = selected_sites[0] if len(selected_sites) == 1 else None

with st.spinner(_("loading", lang)):
    raw = fetch_intensity(
        denominator_type=denominator_type,
        anno_from=anno_from,
        anno_to=anno_to,
        codice_sito=fetch_site,
        gwp_set=gwp_set,
    )

rows: list[dict] = raw.get("rows", [])
df = pd.DataFrame(rows) if rows else pd.DataFrame()

render_context_bar(
    lang=lang,
    year=anno_to,
    gwp=gwp_set,
    role=st.session_state.get("role"),
)

# ---------------------------------------------------------------------------
# VIANO 2025 banner
# ---------------------------------------------------------------------------

visible_sites: list[str] | None = selected_sites if selected_sites else None
# Show banner for any year in the selected range that equals 2025
for _yr in range(anno_from, anno_to + 1):
    if should_show_viano_banner(_yr, visible_sites):
        render_viano_banner(lang)
        break

# ---------------------------------------------------------------------------
# Empty-state / note display
# ---------------------------------------------------------------------------

note: str | None = raw.get("_note") or raw.get("note")
if note:
    st.info(note)

if df.empty:
    st.warning(_("no_data", lang), icon="ℹ️")
    st.divider()
    st.caption(
        f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
        f"GWP set: {gwp_set} | {_('footer_factor_source', lang)} | "
        f"{_('footer_methodology', lang)}"
    )
    st.stop()

# ---------------------------------------------------------------------------
# Line chart — one series per scope_label
# ---------------------------------------------------------------------------

# Okabe-Ito palette cycled across scope_labels
_SCOPE_COLORS: dict[str, str] = {
    "Scope1": BLUE,
    "Scope2_LB": ORANGE,
    "Scope2_MB": BLUISH_GREEN,
    "Scope3": VERMILION,
    "Total": "#000000",
}

y_label: str = _DENOM_UNIT_LABEL.get(denominator_type, "tCO2e / unit")
chart_title: str = f"{_('chart_title_intensity', lang)} · {denom_label} ({gwp_set})"

fig = px.line(
    df,
    x="anno",
    y="intensity_value",
    color="scope_label",
    title=chart_title,
    labels={"intensity_value": y_label, "anno": "Anno", "scope_label": "Scope"},
    color_discrete_map=_SCOPE_COLORS,
    custom_data=[
        "factor_source",
        "factor_version",
        "gwp_set",
        "methodology",
        "denominator_value",
        "denominator_unit",
        "hr_confirmation_date",
    ],
    markers=True,
)

# Build provenance tooltip (FR-23) with CI when available
_has_ci: bool = (
    "confidence_interval_lower" in df.columns
    and df["confidence_interval_lower"].notna().any()
)

hover_template = build_emission_hovertemplate(
    value_label=y_label,
    include_ci=_has_ci,
    mode="line",
)
fig.update_traces(hovertemplate=hover_template)

st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Tabular view + CSV download
# ---------------------------------------------------------------------------

st.subheader(_("table_view", lang))

display_cols: list[str] = [
    c for c in [
        "anno", "codice_sito", "scope_label",
        "intensity_value", "denominator_value", "denominator_unit",
        "gwp_set", "factor_source", "factor_version", "methodology",
        "hr_confirmation_date",
        "confidence_interval_lower", "confidence_interval_upper",
        "correlation_id",
    ]
    if c in df.columns
]

st.dataframe(df[display_cols], use_container_width=True)

from ghg_tool.ui.excel.sheets import _safe_cell_value  # noqa: E402, PLC0415

_csv_df = df[display_cols].copy()
for _col in _csv_df.select_dtypes(include=["object"]).columns:
    _csv_df[_col] = _csv_df[_col].map(_safe_cell_value)
csv_bytes: bytes = _csv_df.to_csv(index=False).encode("utf-8")
st.download_button(
    label=_("download_csv", lang),
    data=csv_bytes,
    file_name=f"intensity_{denominator_type}_{anno_from}_{anno_to}_{gwp_set}.csv",
    mime="text/csv",
)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    f"GWP set: {gwp_set} | {_('footer_factor_source', lang)} | "
    f"{_('footer_methodology', lang)}"
)

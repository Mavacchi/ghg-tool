"""Intensity Metrics page (FR-25, FR-26).

PRE-FLIGHT GATE FAILURE: ``GET /api/v1/intensity`` endpoint is MISSING.
This page displays a prominent notice and static placeholder charts.
BackendAgent must implement the endpoint before live data can be shown here.

When the endpoint becomes available, the STUB_MODE flag should be set to False
and the live fetch uncommented.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Intensity Metrics — GHG", layout="wide")

from ghg_tool.ui.streamlit_app.Home import DASHBOARD_ID, DASHBOARD_VERSION  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.palette import BLUE, ORANGE, BLUISH_GREEN, VERMILION  # noqa: E402

require_auth()
lang = get_lang()

st.title(_("nav_intensity", lang))

# ---------------------------------------------------------------------------
# PRE-FLIGHT GATE FAILURE NOTICE
# ---------------------------------------------------------------------------
st.error(
    "PRE-FLIGHT GATE #1 FAILURE\n\n"
    + _("intensity_endpoint_missing", lang)
    + "\n\nEndpoint required: GET /api/v1/intensity\n"
    "Wire the intensity_service (application/services/intensity_service.py) "
    "into a FastAPI router and register it in api/main.py.",
    icon="🚫",
)

st.divider()

# ---------------------------------------------------------------------------
# Sidebar (still rendered so UI is navigable)
# ---------------------------------------------------------------------------
with st.sidebar:
    gwp_set = st.selectbox("GWP Set", ["AR6", "AR5"])
    denominator = st.selectbox(
        _("intensity_denominator", lang),
        [
            _("intensity_eur_revenue", lang),
            _("intensity_m2_production", lang),
            _("intensity_fte", lang),
            _("intensity_kg_product", lang),
        ],
    )

# ---------------------------------------------------------------------------
# Static placeholder — shows the page layout for future wiring
# ---------------------------------------------------------------------------
st.subheader("Esempio layout (dati placeholder — non usare per reporting)")

import pandas as pd
import plotly.express as px

placeholder_data = pd.DataFrame({
    "anno": [2024, 2025, 2024, 2025],
    "scope2_variant": ["LB", "LB", "MB", "MB"],
    "intensity": [0.82, 0.78, 0.61, 0.59],
    "kpi_code": ["KPI-09", "KPI-09", "KPI-09", "KPI-09"],
    "factor_source": ["PLACEHOLDER", "PLACEHOLDER", "PLACEHOLDER", "PLACEHOLDER"],
    "factor_version": ["N/A", "N/A", "N/A", "N/A"],
    "gwp_set": [gwp_set] * 4,
    "methodology": ["activity-based"] * 4,
})

fig = px.line(
    placeholder_data,
    x="anno",
    y="intensity",
    color="scope2_variant",
    title=f"{_('chart_title_intensity', lang)} — KPI-09 (PLACEHOLDER)",
    labels={"intensity": "tCO2e / t produced", "anno": "Anno"},
    color_discrete_sequence=[BLUE, ORANGE],
    custom_data=["factor_source", "factor_version", "gwp_set", "methodology"],
    markers=True,
)
fig.update_traces(
    hovertemplate=(
        "<b>Anno: %{x}</b><br>"
        "Intensità: %{y:.4f}<br>"
        "Fonte fattore: %{customdata[0]}<br>"
        "Versione: %{customdata[1]}<br>"
        "GWP set: %{customdata[2]}<br>"
        "Metodologia: %{customdata[3]}<extra></extra>"
    )
)
st.plotly_chart(fig, use_container_width=True)

st.info(
    "Quando il BackendAgent implementa GET /api/v1/intensity, "
    "rimuovere il blocco di errore sopra e decommentare il fetch live. "
    "Passare hr_confirmation_date dall'input HR reference table (REV-017)."
)

# ---------------------------------------------------------------------------
# Commented-out live implementation (enable once endpoint exists)
# ---------------------------------------------------------------------------
# with st.spinner(_("loading", lang)):
#     params = {"gwp_set": gwp_set, "denominator": denominator}
#     raw = _safe_get(f"{_get_base_url()}/api/v1/intensity/", params=params)
#     # hr_confirmation_date must be passed from HR reference table per REV-017
#     intensity_rows = raw.get("items", [])
#     df = pd.DataFrame(intensity_rows)
# ... (render line plot from df)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    f"GWP set: {gwp_set} | {_('footer_factor_source', lang)} | "
    f"{_('footer_methodology', lang)}"
)

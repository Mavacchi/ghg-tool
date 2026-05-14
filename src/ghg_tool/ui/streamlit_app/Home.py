"""GHG Dashboard — Home page (Landing + KPI overview).

Displays:
  - Total emissions card (Scope 1 + Scope 2 LB + Scope 3, biogenic memo separately)
  - Tile per scope with delta-from-2024-baseline
  - VIANO 2025 banner (FR-24, MG-12) when conditions are met
  - Biogenic ADR-007 memo card

Footer: "Generated from API v1, GWP set: AR6, factor_source: ISPRA 2024 + IEA 2024,
methodology: GHG Protocol Corporate Standard"
"""

from __future__ import annotations

import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    COMPANY_NAME,
    COMPANY_SHORT,
    DASHBOARD_ID,
    DASHBOARD_VERSION,
    FAVICON_PATH,
    KNOWN_SITES,
    LOGO_PATH,
    PRODUCT_NAME,
)

# Favicon falls back to a Unicode glyph if the PNG is missing in the
# runtime image (e.g. tests run from a partial checkout).
_page_icon: str | object = str(FAVICON_PATH) if FAVICON_PATH.exists() else "🏭"

st.set_page_config(
    page_title=f"{PRODUCT_NAME} — {COMPANY_SHORT}",
    page_icon=_page_icon,
    layout="wide",
    initial_sidebar_state="expanded",
)

# Show the Gresmalt logo top-left + collapsed-sidebar icon.
# ``st.logo`` is a no-op pre-1.35; guarded for older Streamlit just in case.
if hasattr(st, "logo") and LOGO_PATH.exists():
    st.logo(str(LOGO_PATH), icon_image=str(FAVICON_PATH) if FAVICON_PATH.exists() else None)

# Must import after set_page_config
from ghg_tool.ui.streamlit_app.lib.auth import (  # noqa: E402
    get_lang,
    get_token,
    is_demo_mode,
    logout,
    render_demo_mode_banner,
    require_auth,
)
from ghg_tool.ui.streamlit_app.lib.banner import render_viano_banner, should_show_viano_banner  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.help import _help  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.api_client import fetch_kpis, emissions_to_dataframe  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.palette import SCOPE_COLOURS, BLUE, VERMILION, BLUISH_GREEN, ORANGE  # noqa: E402

# ---------------------------------------------------------------------------
# Sidebar — language toggle + auth
# ---------------------------------------------------------------------------
with st.sidebar:
    lang_options = {"Italiano": "it", "English": "en"}
    lang_label = st.selectbox("Language / Lingua", list(lang_options.keys()), index=0)
    lang = lang_options[lang_label]
    st.session_state["lang"] = lang

    st.divider()

    import datetime as _dt  # noqa: PLC0415

    year_options = list(range(2024, 2027))
    _current_year = _dt.date.today().year
    _default_year_index = (
        year_options.index(_current_year) if _current_year in year_options else len(year_options) - 1
    )
    selected_year = st.selectbox(
        _("year_filter", lang), year_options, index=_default_year_index,
        help=_help("anno_fiscale", lang),
    )

    gwp_options = ["AR6", "AR5"]
    selected_gwp = st.selectbox(
        "GWP Set", gwp_options, index=0,
        help=_help("gwp", lang),
    )

    st.divider()
    if get_token():
        if st.button(_("logout_btn", lang)):
            logout()
            st.rerun()

# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------
require_auth(lang)

# ---------------------------------------------------------------------------
# Page title — "Carbontrace · Gresmalt"
# ---------------------------------------------------------------------------
st.title(f"{PRODUCT_NAME} · {COMPANY_SHORT}")
st.caption(COMPANY_NAME)
st.subheader(f"{_('nav_home', lang)} — {selected_year}")

# Demo-mode banner (visible only when GHG_DEMO_MODE is enabled and the
# session is currently using a demo token, so users never confuse the
# bypass with a real authenticated session).
if is_demo_mode():
    render_demo_mode_banner(lang)

# ---------------------------------------------------------------------------
# VIANO banner check (FR-24)
# ---------------------------------------------------------------------------
if should_show_viano_banner(selected_year, list(KNOWN_SITES)):
    render_viano_banner(lang)

# ---------------------------------------------------------------------------
# KPI data fetch
# ---------------------------------------------------------------------------
with st.spinner(_("loading", lang)):
    kpi_data = fetch_kpis(anno=selected_year, gwp_set=selected_gwp)

kpis = kpi_data.get("kpis", [])
as_of = kpi_data.get("as_of", "N/A")

# Aggregate KPIs by scope
scope_totals: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0}
scope2_mb_total = 0.0
biogenic_total = 0.0

for row in kpis:
    scope_val = row.get("scope")
    tco2e = float(row.get("tco2e") or 0.0)
    sub_scope = row.get("sub_scope", "")
    if scope_val in (1, 2, 3):
        # For scope 2, only sum LB for the main total
        if scope_val == 2:
            if sub_scope == "LB":
                scope_totals[2] += tco2e
            elif sub_scope == "MB":
                scope2_mb_total += tco2e
        else:
            scope_totals[scope_val] += tco2e
    if sub_scope == "biogenic":
        biogenic_total += tco2e

total_lb = sum(scope_totals.values())

# ---------------------------------------------------------------------------
# Metric cards
# ---------------------------------------------------------------------------
col_total, col_s1, col_s2lb, col_s2mb, col_s3 = st.columns(5)

with col_total:
    st.metric(
        label=_("total_emissions", lang),
        value=f"{total_lb:,.1f} tCO2e",
        help=_help("tco2e", lang),
    )

with col_s1:
    st.metric(
        label=_("scope1_total", lang),
        value=f"{scope_totals[1]:,.1f}",
        help=_help("scope1", lang),
    )

with col_s2lb:
    st.metric(
        label=_("scope2_lb", lang),
        value=f"{scope_totals[2]:,.1f}",
        help=_help("scope2_lb", lang),
    )

with col_s2mb:
    st.metric(
        label=_("scope2_mb", lang),
        value=f"{scope2_mb_total:,.1f}",
        help=_help("scope2_mb", lang),
    )

with col_s3:
    st.metric(
        label=_("scope3_total", lang),
        value=f"{scope_totals[3]:,.1f}",
        help=_help("scope3", lang),
    )

# ---------------------------------------------------------------------------
# Biogenic memo card (ADR-007)
# ---------------------------------------------------------------------------
with st.expander(f"⚠️ {_('biogenic_memo', lang)}", expanded=False):
    st.info(_("biogenic_adv007", lang))
    if biogenic_total > 0:
        st.metric(
            "CO2 Biogenico (tonne)", f"{biogenic_total:,.1f}",
            help=_help("biogenic", lang),
        )
    else:
        st.caption("Nessuna emissione biogenica nel periodo selezionato.")

# ---------------------------------------------------------------------------
# Scope breakdown bar chart
# ---------------------------------------------------------------------------
if kpis:
    import pandas as pd
    import plotly.express as px
    from ghg_tool.ui.streamlit_app.lib.tooltips import build_emission_hovertemplate

    df = pd.DataFrame(kpis)
    if not df.empty and "tco2e" in df.columns:
        df["tco2e"] = pd.to_numeric(df["tco2e"], errors="coerce").fillna(0.0)
        df["scope_label"] = df["scope"].apply(lambda s: f"Scope {s}" if s else "N/A")

        # Ensure customdata columns exist with fallback
        for col in ["factor_source", "factor_version", "gwp_set", "methodology", "sub_scope"]:
            if col not in df.columns:
                df[col] = "N/A"

        fig = px.bar(
            df,
            x="scope_label",
            y="tco2e",
            color="sub_scope",
            title=_("chart_title_scope123", lang) + f" — {selected_year}",
            labels={"tco2e": "tCO2e", "scope_label": "Scope", "sub_scope": "Sub-scope"},
            color_discrete_sequence=[VERMILION, BLUE, BLUISH_GREEN, ORANGE],
            custom_data=["factor_source", "factor_version", "gwp_set",
                         "methodology", "sub_scope"],
        )
        fig.update_traces(
            hovertemplate=build_emission_hovertemplate(mode="bar")
        )
        fig.update_layout(
            barmode="stack",
            legend_title_text="Sub-scope",
            font={"family": "Arial, sans-serif"},
        )
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info(_("no_data", lang))

# ---------------------------------------------------------------------------
# Footer (mandatory tracibility per FR-23)
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | "
    f"{_('footer_dashboard_version', lang)}{DASHBOARD_VERSION} | "
    f"{_('footer_api_version', lang)} | "
    f"{_('footer_gwp_set', lang)}: {selected_gwp} | "
    f"{_('footer_factor_source', lang)} | "
    f"{_('footer_methodology', lang)} | "
    f"as_of: {as_of}"
)

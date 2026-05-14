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
    KNOWN_SITES,
    PRODUCT_NAME,
    page_icon,
)

st.set_page_config(
    page_title=f"{PRODUCT_NAME} · {COMPANY_SHORT}",
    page_icon=page_icon(),
    layout="wide",
    initial_sidebar_state="expanded",
)

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
from ghg_tool.ui.streamlit_app.lib.brand import apply_brand_chrome, render_context_bar, render_role_chip  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.filters import sidebar_gwp_filter, sidebar_year_filter  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.help import _help  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.api_client import fetch_kpis, emissions_to_dataframe  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.palette import SCOPE_COLOURS, BLUE, VERMILION, BLUISH_GREEN, ORANGE  # noqa: E402

apply_brand_chrome()

# ---------------------------------------------------------------------------
# Sidebar — language toggle + auth
# ---------------------------------------------------------------------------
with st.sidebar:
    # Language selector is rendered BEFORE the auth gate so the login form
    # can show its own labels in the chosen language.
    lang_options = {"Italiano": "it", "English": "en"}
    lang_label = st.selectbox("Language / Lingua", list(lang_options.keys()), index=0)
    lang = lang_options[lang_label]
    st.session_state["lang"] = lang

# ---------------------------------------------------------------------------
# Auth gate. Year and GWP filters are rendered AFTER auth so unauthenticated
# users don't see disabled filters they cannot use yet.
# ---------------------------------------------------------------------------
require_auth(lang)

render_role_chip(st.session_state.get("role"), lang)

with st.sidebar:
    st.divider()
    selected_year = sidebar_year_filter(lang)
    selected_gwp = sidebar_gwp_filter(lang)

    st.divider()
    if st.button(_("logout_btn", lang)):
        logout()
        st.rerun()

# ---------------------------------------------------------------------------
# Hero header. Product name only, then tagline, then company name as
# tertiary line. Year context is surfaced by the sidebar year selector,
# so we do not repeat it as a subheader here.
# ---------------------------------------------------------------------------
render_context_bar(
    lang=lang,
    year=selected_year,
    gwp=selected_gwp,
    role=st.session_state.get("role"),
)

_hero_tagline = _("hero_tagline", lang)
st.markdown(
    f"""
<div class="carbontrace-hero">
  <div class="ct-brand-rule" aria-hidden="true"></div>
  <h1 class="ct-hero-title" id="main">{PRODUCT_NAME}</h1>
  <p class="ct-hero-tagline">{_hero_tagline}</p>
  <p class="ct-hero-company">{COMPANY_NAME}</p>
</div>
""",
    unsafe_allow_html=True,
)

# Demo-mode banner (visible only when GHG_DEMO_MODE is enabled and the
# session is currently using a demo token, so users never confuse the
# bypass with a real authenticated session).
if is_demo_mode():
    render_demo_mode_banner(lang)

# First-visit onboarding card. The dismiss flag is per-session so the
# card returns after each fresh login; not stored server-side.
if not st.session_state.get("home_onboarding_dismissed", False):
    with st.container(border=True):
        ob_l, ob_r = st.columns([5, 1])
        with ob_l:
            st.markdown(f"### 👋 {_('onboarding_title', lang)}")
            st.markdown(_("onboarding_body", lang))
        with ob_r:
            if st.button(_("onboarding_dismiss", lang), key="dismiss_onboarding"):
                st.session_state["home_onboarding_dismissed"] = True
                st.rerun()

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
# Empty state. When the ledger has no rows for the selected filters,
# show a clear guided CTA instead of five "0.0 tCO2e" tiles that read
# as broken/loading.
# ---------------------------------------------------------------------------
if not kpis or (total_lb <= 0.0 and scope2_mb_total <= 0.0):
    with st.container(border=True):
        st.subheader(_("empty_kpi_title", lang))
        st.markdown(_("empty_kpi_body", lang))
        if hasattr(st, "page_link"):
            st.page_link(
                "pages/4_Data_Entry.py",
                label=_("empty_kpi_cta", lang),
                icon="➕",
            )
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
    st.stop()

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
        st.caption(_("no_biogenic_in_period", lang))

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
            title=_("chart_title_scope123", lang) + f" · {selected_year}",
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

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
    page_title=PRODUCT_NAME,
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
# Time-series trend: total emissions over the last 5 reporting years.
#
# Pulls a separate fetch_kpis(anno=year) for each year in the window
# and aggregates Scope 1 + Scope 2 LB + Scope 3 into a single total.
# Behind st.cache_data so re-renders are cheap.
# ---------------------------------------------------------------------------
import pandas as _pd  # noqa: PLC0415
import plotly.graph_objects as _go  # noqa: PLC0415


@st.cache_data(ttl=300, show_spinner=False)
def _trend_for_years(years: tuple[int, ...], gwp_set: str) -> _pd.DataFrame:
    """Return a small DataFrame with one row per year and a total column."""
    rows: list[dict[str, float | int]] = []
    for yr in years:
        data = fetch_kpis(anno=yr, gwp_set=gwp_set)
        s1 = s2_lb = s3 = 0.0
        for r in data.get("kpis", []):
            tco2e = float(r.get("tco2e") or 0.0)
            sc = r.get("scope")
            sub = r.get("sub_scope", "")
            if sc == 1:
                s1 += tco2e
            elif sc == 2 and sub == "LB":
                s2_lb += tco2e
            elif sc == 3:
                s3 += tco2e
        rows.append(
            {"year": yr, "scope1": s1, "scope2_lb": s2_lb, "scope3": s3,
             "total": s1 + s2_lb + s3}
        )
    return _pd.DataFrame(rows)


_trend_window = tuple(sorted({selected_year - i for i in range(5) if selected_year - i >= 2020}))
_trend_df = _trend_for_years(_trend_window, selected_gwp)
if not _trend_df.empty and _trend_df["total"].sum() > 0:
    _fig_trend = _go.Figure()
    _fig_trend.add_trace(
        _go.Scatter(
            x=_trend_df["year"],
            y=_trend_df["total"],
            mode="lines+markers",
            line={"color": "#788B99", "width": 2},
            marker={"size": 8, "color": "#788B99"},
            name=_("total_emissions", lang),
            hovertemplate="%{x}<br><b>%{y:,.1f} tCO2e</b><extra></extra>",
        )
    )
    _fig_trend.update_layout(
        height=220,
        margin={"l": 0, "r": 0, "t": 30, "b": 0},
        title=_("trend_chart_title", lang),
        title_font={"size": 14, "color": "#1a1a1a"},
        font={"family": "Inter, sans-serif"},
        showlegend=False,
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        xaxis={"showgrid": False, "tickmode": "linear"},
        yaxis={
            "showgrid": True, "gridcolor": "#ECE5DC",
            "title": "tCO2e",
            "rangemode": "tozero",
        },
    )
    st.plotly_chart(_fig_trend, use_container_width=True)


# ---------------------------------------------------------------------------
# Metric cards (drill-through enabled: a hidden "→ Drill-down" page_link
# under each card lets the user jump to a filtered detail view.)
# ---------------------------------------------------------------------------
col_total, col_s1, col_s2lb, col_s2mb, col_s3 = st.columns(5)

with col_total:
    st.metric(
        label=_("total_emissions", lang),
        value=f"{total_lb:,.1f} tCO2e",
        help=_help("tco2e", lang),
    )

def _drill_link(scope: int) -> None:
    """Render a small "Esamina" page_link below a metric card.

    The target is Drill-Down with the scope filter pre-seeded via
    session_state so the user lands on a filtered view in one click.
    """
    if not hasattr(st, "page_link"):
        return
    # The Drill-Down sidebar reads its scope selectbox from a Streamlit
    # widget key, so we cannot pre-seed easily. We instead set a
    # well-known session-state hint that the Drill-Down page reads as
    # an OPT-IN default on first render.
    if st.button(
        _("drill_through", lang), key=f"drill_{scope}",
        type="secondary", use_container_width=True,
    ):
        st.session_state["drilldown_scope_hint"] = scope
        st.switch_page("pages/1_Drill_Down.py")


with col_s1:
    st.metric(
        label=_("scope1_total", lang),
        value=f"{scope_totals[1]:,.1f}",
        help=_help("scope1", lang),
    )
    _drill_link(1)

with col_s2lb:
    st.metric(
        label=_("scope2_lb", lang),
        value=f"{scope_totals[2]:,.1f}",
        help=_help("scope2_lb", lang),
    )
    _drill_link(2)

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
    _drill_link(3)

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

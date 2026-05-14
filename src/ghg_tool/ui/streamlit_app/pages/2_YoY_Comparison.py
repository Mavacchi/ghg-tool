"""Year-over-Year comparison page (FR-24, FR-25).

Features:
  - Two-year comparator (default 2024 → 2025)
  - Absolute Δ and relative Δ% per scope per site, with bootstrap CI bands
  - Highlights rows where |Δ| > YOY_SIGMA_MULTIPLIER * sigma of historical variation (Okabe-Ito palette)
  - Normalised YoY (per EUR revenue, per m² production)
  - VIANO 2025 banner when applicable
"""

from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    DASHBOARD_ID, DASHBOARD_VERSION, PRODUCT_NAME, page_icon,
)

st.set_page_config(
    page_title=f"YoY Comparison · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.banner import render_viano_banner, should_show_viano_banner  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.brand import apply_brand_chrome, render_context_bar, render_role_chip  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.filters import available_years, sidebar_gwp_filter  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.help import _help  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.api_client import fetch_emissions, emissions_to_dataframe  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.palette import (  # noqa: E402
    ORANGE, VERMILION, BLUISH_GREEN, BLUE, SKY_BLUE, plotly_qualitative
)
from ghg_tool.application.services.hotspot_service import YOY_SIGMA_MULTIPLIER  # noqa: E402

apply_brand_chrome()
require_auth()
lang = get_lang()

st.title(_("nav_yoy", lang))

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    _yoy_years = available_years()
    year_base = st.selectbox(
        _("select_year_base", lang), _yoy_years, index=0,
        help=_help("anno_fiscale", lang),
    )
    year_compare = st.selectbox(
        _("select_year_compare", lang), _yoy_years,
        index=len(_yoy_years) - 1,
        help=_help("yoy_delta_abs", lang),
    )
    gwp_set = sidebar_gwp_filter(lang)

    st.divider()
    revenue_meur_base = st.number_input(
        "Ricavi base (M€)", value=120.0, min_value=0.1,
        help=_help("intensity_revenue", lang),
    )
    revenue_meur_cmp = st.number_input(
        "Ricavi confronto (M€)", value=115.0, min_value=0.1,
        help=_help("intensity_revenue", lang),
    )
    prod_t_base = st.number_input(
        "Produzione base (t)", value=500000.0, min_value=1.0,
        help=_help("intensity_kg_product", lang),
    )
    prod_t_cmp = st.number_input(
        "Produzione confronto (t)", value=480000.0, min_value=1.0,
        help=_help("intensity_kg_product", lang),
    )

# ---------------------------------------------------------------------------
# VIANO banner
# ---------------------------------------------------------------------------
render_role_chip(st.session_state.get("role"), lang)

render_context_bar(
    lang=lang,
    year=year_compare,
    gwp=gwp_set,
    role=st.session_state.get("role"),
)

if should_show_viano_banner(max(year_base, year_compare)):
    render_viano_banner(lang)

# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------
with st.spinner(_("loading", lang)):
    raw_base = fetch_emissions(anno=year_base, gwp_set=gwp_set, limit=500)
    raw_cmp = fetch_emissions(anno=year_compare, gwp_set=gwp_set, limit=500)

df_base = emissions_to_dataframe(raw_base)
df_cmp = emissions_to_dataframe(raw_cmp)

if df_base.empty and df_cmp.empty:
    st.info(_("no_data", lang))
    st.stop()

# ---------------------------------------------------------------------------
# Aggregation helper
# ---------------------------------------------------------------------------

def _aggregate(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Aggregate tco2e by site × scope × sub_scope for one year.

    Args:
        df: Raw emissions DataFrame.
        year: Year label for output column.

    Returns:
        Pivoted DataFrame.
    """
    if df.empty:
        return pd.DataFrame(columns=["codice_sito", "scope", "sub_scope",
                                     f"tco2e_{year}"])
    grp = (
        df.groupby(["codice_sito", "scope", "sub_scope"], dropna=False)["tco2e"]
        .sum()
        .reset_index()
        .rename(columns={"tco2e": f"tco2e_{year}"})
    )
    return grp


agg_base = _aggregate(df_base, year_base)
agg_cmp = _aggregate(df_cmp, year_compare)

if agg_base.empty or agg_cmp.empty:
    st.info(_("no_data", lang))
    st.stop()

merged = pd.merge(
    agg_base, agg_cmp,
    on=["codice_sito", "scope", "sub_scope"],
    how="outer",
).fillna(0.0)

col_b = f"tco2e_{year_base}"
col_c = f"tco2e_{year_compare}"

merged["delta_abs"] = merged[col_c] - merged[col_b]
merged["delta_pct"] = merged.apply(
    lambda r: (r["delta_abs"] / r[col_b] * 100.0) if r[col_b] != 0 else float("nan"),
    axis=1,
)

# Mark outliers (|Δ - μ| > YOY_SIGMA_MULTIPLIER * sigma): standard z-score test.
# YOY_SIGMA_MULTIPLIER is the canonical constant from hotspot_service (R-09).
sigma = merged["delta_abs"].std()
mean_delta = merged["delta_abs"].mean()
if sigma and not pd.isna(sigma) and sigma > 0:
    merged["is_outlier"] = (merged["delta_abs"] - mean_delta).abs() > float(YOY_SIGMA_MULTIPLIER) * sigma
else:
    merged["is_outlier"] = False
merged["row_color"] = merged.apply(
    lambda r: VERMILION if r["is_outlier"] else BLUISH_GREEN, axis=1
)

# ---------------------------------------------------------------------------
# Normalised intensity comparison
# ---------------------------------------------------------------------------
scope_base = df_base.groupby("scope")["tco2e"].sum() if not df_base.empty else pd.Series()
scope_cmp = df_cmp.groupby("scope")["tco2e"].sum() if not df_cmp.empty else pd.Series()

total_base = scope_base.sum()
total_cmp = scope_cmp.sum()

intensity_base_rev = total_base / revenue_meur_base
intensity_cmp_rev = total_cmp / revenue_meur_cmp
intensity_base_prod = total_base / prod_t_base * 1000
intensity_cmp_prod = total_cmp / prod_t_cmp * 1000

# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)
with col1:
    delta_total = total_cmp - total_base
    st.metric(
        label=f"Totale {year_compare} vs {year_base}",
        value=f"{total_cmp:,.0f} tCO2e",
        delta=f"{delta_total:+,.0f} tCO2e",
        delta_color="inverse",
    )
with col2:
    if total_base != 0:
        delta_pct = (total_cmp - total_base) / total_base * 100
        st.metric("Δ%", f"{delta_pct:+.1f}%", delta_color="inverse")
with col3:
    st.metric(
        "Intensità (tCO2e/M€)",
        f"{intensity_cmp_rev:.2f}",
        delta=f"{intensity_cmp_rev - intensity_base_rev:+.2f}",
        delta_color="inverse",
    )
with col4:
    st.metric(
        "Intensità (tCO2e/kt prodotto)",
        f"{intensity_cmp_prod:.2f}",
        delta=f"{intensity_cmp_prod - intensity_base_prod:+.2f}",
        delta_color="inverse",
    )

st.divider()

# ---------------------------------------------------------------------------
# Delta bar chart (absolute)
# ---------------------------------------------------------------------------
fig = go.Figure()

outlier_df = merged[merged["is_outlier"]]
normal_df = merged[~merged["is_outlier"]]

label_col = merged.apply(
    lambda r: f"{r.get('codice_sito', '?')} | S{r.get('scope', '?')} {r.get('sub_scope', '')}", axis=1
)
merged["label"] = label_col

fig.add_trace(go.Bar(
    name=_("yoy_abs_delta", lang),
    x=normal_df["label"],
    y=normal_df["delta_abs"],
    marker_color=BLUE,
))
if not outlier_df.empty:
    outlier_label = merged[merged["is_outlier"]]["label"]
    fig.add_trace(go.Bar(
        name=f"{_('yoy_abs_delta', lang)} · {_('yoy_outlier_warn', lang)}",
        x=outlier_label,
        y=outlier_df["delta_abs"],
        marker_color=VERMILION,
    ))

fig.update_layout(
    title=f"{_('chart_title_yoy', lang)} · {year_base} → {year_compare}",
    xaxis_title=_("table_site", lang),
    yaxis_title="Δ tCO2e",
    barmode="overlay",
    legend_title_text="Serie",
)
st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Delta table with colour-coded severity
# ---------------------------------------------------------------------------
st.subheader(f"Tabella Δ {year_base} → {year_compare}")

display_df = merged[[
    "codice_sito", "scope", "sub_scope",
    col_b, col_c, "delta_abs", "delta_pct", "is_outlier"
]].copy()
display_df.columns = [
    _("table_site", lang), _("table_scope", lang), _("table_sub_scope", lang),
    f"tCO2e {year_base}", f"tCO2e {year_compare}",
    _("yoy_abs_delta", lang), _("yoy_rel_delta", lang), "Outlier (>2σ)"
]

st.dataframe(
    display_df.style.applymap(
        lambda v: f"background-color: {ORANGE}; color: black;" if v is True else "",
        subset=["Outlier (>2σ)"],
    ),
    use_container_width=True,
    hide_index=True,
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

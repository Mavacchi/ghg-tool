"""Compare page - side-by-side comparison of two slices.

Two modes selectable from a radio:

  1. "Anno vs anno" - same site (or all sites), two reporting years
     side-by-side with delta column.
  2. "Sito vs sito" - same year, two sites side-by-side with delta
     column (per scope).

Both modes reuse the existing fetch_emissions endpoint and aggregate
client-side. Designed as a power-user view; the regular YoY page
covers the most common single-year delta narrative.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    DASHBOARD_ID,
    DASHBOARD_VERSION,
    KNOWN_SITES,
    PRODUCT_NAME,
    page_icon,
)

st.set_page_config(
    page_title=f"Confronto · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

from ghg_tool.ui.streamlit_app.lib.api_client import fetch_emissions  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.brand import (  # noqa: E402
    apply_brand_chrome,
    render_context_bar,
    render_role_chip,
)
from ghg_tool.ui.streamlit_app.lib.exports import render_download_row  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.filters import available_years  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.help import _help  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402

apply_brand_chrome()
require_auth()
lang = get_lang()

render_role_chip(st.session_state.get("role"), lang)

st.title(_("compare_title", lang))
st.caption(_("compare_caption", lang))

render_context_bar(
    lang=lang,
    year=None,
    gwp=None,
    role=st.session_state.get("role"),
)


def _aggregate(rows: list[dict]) -> pd.DataFrame:
    """Group emissions by (scope, sub_scope, codice_sito) and sum tco2e."""
    if not rows:
        return pd.DataFrame(columns=["scope", "sub_scope", "codice_sito", "tco2e"])
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["tco2e"] = pd.to_numeric(df.get("tco2e", 0), errors="coerce").fillna(0.0)
    return (
        df.groupby(["scope", "sub_scope", "codice_sito"], dropna=False, as_index=False)[
            "tco2e"
        ]
        .sum()
    )


def _merge_for_compare(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    label_a: str,
    label_b: str,
) -> pd.DataFrame:
    """Outer-join two aggregated frames on the grouping key.

    Returns one row per grouping key with two value columns (label_a, label_b)
    and a delta column. NaNs become 0.0 in the math but are preserved in the
    display so the user sees "missing on this side" clearly.
    """
    key = ["scope", "sub_scope", "codice_sito"]
    a = df_a.rename(columns={"tco2e": label_a})
    b = df_b.rename(columns={"tco2e": label_b})
    out = pd.merge(a, b, on=key, how="outer")
    out[label_a] = out[label_a].fillna(0.0)
    out[label_b] = out[label_b].fillna(0.0)
    out["delta"] = out[label_b] - out[label_a]
    out["delta_pct"] = out.apply(
        lambda r: (
            (r["delta"] / r[label_a] * 100.0) if r[label_a] else float("nan")
        ),
        axis=1,
    )
    out = out.sort_values(by="delta", key=lambda s: s.abs(), ascending=False)
    return out


# ---------------------------------------------------------------------------
# Mode selector
# ---------------------------------------------------------------------------
mode = st.radio(
    _("compare_mode_label", lang),
    options=("year_vs_year", "site_vs_site"),
    format_func=lambda m: _("compare_mode_" + m, lang),
    horizontal=True,
)

years = available_years()
sites = ["(tutti)"] + list(KNOWN_SITES)

if mode == "year_vs_year":
    cols = st.columns(3)
    with cols[0]:
        year_a = st.selectbox(
            _("compare_year_a", lang), years, index=0, key="cmp_year_a",
            help=_help("anno_fiscale", lang),
        )
    with cols[1]:
        year_b = st.selectbox(
            _("compare_year_b", lang), years,
            index=len(years) - 1, key="cmp_year_b",
            help=_help("anno_fiscale", lang),
        )
    with cols[2]:
        site_pick = st.selectbox(
            _("compare_site_filter", lang), sites, key="cmp_site_pick",
            help=_help("codice_sito", lang),
        )
    site_filter = None if site_pick == "(tutti)" else site_pick
    label_a = f"{year_a} (tCO2e)"
    label_b = f"{year_b} (tCO2e)"
    raw_a = fetch_emissions(anno=int(year_a), codice_sito=site_filter, limit=500)
    raw_b = fetch_emissions(anno=int(year_b), codice_sito=site_filter, limit=500)
    rows_a = raw_a if isinstance(raw_a, list) else []
    rows_b = raw_b if isinstance(raw_b, list) else []

else:  # site_vs_site
    cols = st.columns(3)
    with cols[0]:
        year_pick = st.selectbox(
            _("compare_year_filter", lang), years, key="cmp_year_pick",
            help=_help("anno_fiscale", lang),
        )
    with cols[1]:
        site_a = st.selectbox(
            _("compare_site_a", lang), list(KNOWN_SITES), key="cmp_site_a",
            help=_help("codice_sito", lang),
        )
    with cols[2]:
        site_b = st.selectbox(
            _("compare_site_b", lang), list(KNOWN_SITES),
            index=1, key="cmp_site_b",
            help=_help("codice_sito", lang),
        )
    label_a = f"{site_a} (tCO2e)"
    label_b = f"{site_b} (tCO2e)"
    raw_a = fetch_emissions(anno=int(year_pick), codice_sito=site_a, limit=500)
    raw_b = fetch_emissions(anno=int(year_pick), codice_sito=site_b, limit=500)
    rows_a = raw_a if isinstance(raw_a, list) else []
    rows_b = raw_b if isinstance(raw_b, list) else []

# ---------------------------------------------------------------------------
# Aggregate + merge + render
# ---------------------------------------------------------------------------

df_a = _aggregate(rows_a)
df_b = _aggregate(rows_b)

if df_a.empty and df_b.empty:
    st.info(_("compare_no_data", lang))
else:
    merged = _merge_for_compare(df_a, df_b, label_a, label_b)

    # Headline KPIs.
    total_a = float(merged[label_a].sum())
    total_b = float(merged[label_b].sum())
    total_delta = total_b - total_a
    total_pct = (total_delta / total_a * 100.0) if total_a else 0.0

    k1, k2, k3 = st.columns(3)
    with k1:
        st.metric(label_a, f"{total_a:,.1f}")
    with k2:
        st.metric(
            label_b, f"{total_b:,.1f}",
            delta=f"{total_delta:+,.1f} ({total_pct:+.1f}%)",
            delta_color="inverse",
        )
    with k3:
        st.metric(_("compare_delta_label", lang), f"{total_delta:+,.1f}",
                  help=_help("yoy_delta_abs", lang))

    st.divider()

    # Per-row table (sorted by abs(delta) descending so the biggest movers
    # are at the top - typical CFO question is "what changed the most").
    display = merged[[
        "scope", "sub_scope", "codice_sito",
        label_a, label_b, "delta", "delta_pct",
    ]].copy()
    display = display.rename(columns={
        "scope": _("table_scope", lang),
        "sub_scope": _("table_sub_scope", lang),
        "codice_sito": _("table_site", lang),
        "delta": _("compare_delta_label", lang),
        "delta_pct": _("compare_delta_pct_label", lang),
    })
    render_download_row(display, basename="compare", lang=lang, key_prefix="cmp")
    st.dataframe(display, use_container_width=True, hide_index=True)

st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    f"{_('footer_factor_source', lang)} | "
    f"{_('footer_methodology', lang)}"
)

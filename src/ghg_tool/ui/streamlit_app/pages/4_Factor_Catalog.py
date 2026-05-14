"""Factor Catalog browser page (FR-04, FR-29).

Read-only browsable table over the factor catalog.
Filters: regulatory_stream, gwp_set, source, scope, effective_from range.
Displays: factor_id, source, version, effective_from, value, unit,
          uncertainty %, biogenic companion value (ADR-007).
"""

from __future__ import annotations

import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    DASHBOARD_ID, DASHBOARD_VERSION, PRODUCT_NAME, page_icon,
)

st.set_page_config(
    page_title=f"Factor Catalog — {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.help import _help  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.brand import apply_brand_chrome  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.api_client import fetch_factor_catalog  # noqa: E402

apply_brand_chrome()
require_auth()
lang = get_lang()

st.title(_("nav_factor_catalog", lang))

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
with st.sidebar:
    scope_opts = ["Tutti / All", "1", "2", "3"]
    scope_label = st.selectbox(
        _("scope_filter", lang), scope_opts,
        help=_help("scope1", lang),
    )
    scope_filter: int | None = int(scope_label) if scope_label.isdigit() else None

    source_opts = ["", "DEFRA", "ISPRA", "IEA", "ecoinvent",
                   "EXIOBASE", "CDP", "IPCC", "AIB", "EPD", "GHGProtocol"]
    source_filter = st.selectbox(
        _("factor_source_col", lang), source_opts,
        help=_help("factor_source", lang),
    )

    gwp_opts = ["", "AR6", "AR5", "n/a"]
    gwp_filter = st.selectbox(
        "GWP Set", gwp_opts,
        help=_help("gwp", lang),
    )

    published_only = st.checkbox(
        "Solo pubblicati / Published only", value=True,
        help=_help("factor_version", lang),
    )

# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------
with st.spinner(_("loading", lang)):
    raw = fetch_factor_catalog(
        scope=scope_filter,
        source=source_filter or None,
        gwp_set=gwp_filter or None,
        limit=200,
    )

import pandas as pd

if not raw:
    st.info(_("no_data", lang))
else:
    df = pd.DataFrame(raw)

    if published_only and "is_published" in df.columns:
        df = df[df["is_published"] == True]  # noqa: E712

    display_cols = [
        c for c in [
            "factor_id", "version", "substance", "scope", "category",
            "source", "value", "unit", "gwp_set", "valid_from", "valid_to",
            "biogenic_co2_kg_per_unit", "applicability_note", "pdf_source_uri",
            "is_published", "is_tbc",
        ] if c in df.columns
    ]

    col_labels = {
        "factor_id": "Factor ID",
        "version": _("factor_version_col", lang),
        "substance": "Sostanza",
        "scope": _("table_scope", lang),
        "category": "Categoria",
        "source": _("factor_source_col", lang),
        "value": "Valore",
        "unit": "Unità",
        "gwp_set": "GWP Set",
        "valid_from": _("factor_effective_from", lang),
        "valid_to": "Valido fino a",
        "biogenic_co2_kg_per_unit": "CO2 Biogenico (kg/unità)",
        "applicability_note": "Note applicabilità",
        "pdf_source_uri": _("factor_uri", lang),
        "is_published": "Pubblicato",
        "is_tbc": "TBC",
    }

    st.dataframe(
        df[display_cols].rename(columns=col_labels),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(f"Totale fattori: {len(df)}")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    f"GWP set: AR6 (default) | {_('footer_factor_source', lang)} | "
    f"{_('footer_methodology', lang)}"
)

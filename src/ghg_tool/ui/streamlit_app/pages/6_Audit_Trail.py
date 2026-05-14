"""Audit Trail page — paginated corrections log (FR-22).

Displays: emission_id, predecessor_id (superseded_by), calc_timestamp,
valid_from, valid_to, who (created_by), correlation_id, correction_reason.
Uses AuditTrailResponse from kpi_schemas.py.
"""

from __future__ import annotations

import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    DASHBOARD_ID, DASHBOARD_VERSION, PRODUCT_NAME, page_icon,
)

st.set_page_config(
    page_title=f"Audit Trail · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.help import _help  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.brand import apply_brand_chrome  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.api_client import fetch_audit_trail  # noqa: E402

apply_brand_chrome()
require_auth()
lang = get_lang()

st.title(_("nav_audit_trail", lang))

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    year_opts: list[int | None] = [None, 2024, 2025]
    year_labels = ["Tutti / All"] + [str(y) for y in year_opts[1:]]
    year_choice = st.selectbox(
        _("year_filter", lang), year_labels,
        help=_help("audit_correlation_id", lang),
    )
    anno_filter: int | None = int(year_choice) if year_choice != "Tutti / All" else None

    site_opts = ["", "IANO", "VIANO", "VIANO_GARGOLA", "CASALGRANDE",
                 "FIORANO", "SASSUOLO", "FRASSINORO"]
    site_filter = st.selectbox(
        _("site_filter", lang), site_opts,
        help=_help("codice_sito", lang),
    )

    page_size = st.number_input("Righe per pagina", min_value=10, max_value=500,
                                value=50, step=10)

# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------
with st.spinner(_("loading", lang)):
    raw = fetch_audit_trail(
        anno=anno_filter,
        codice_sito=site_filter or None,
        limit=int(page_size),
    )

import pandas as pd

entries = raw.get("entries", [])
pagination = raw.get("pagination", {})
correlation_id_resp = raw.get("correlation_id", "N/A")

if not entries:
    st.info(_("no_data", lang))
else:
    df = pd.DataFrame(entries)

    # Pagination info
    count = pagination.get("count", len(df))
    next_cursor = pagination.get("next_cursor")
    st.caption(
        f"Righe visualizzate: {count} | Correlation ID richiesta: {correlation_id_resp}"
    )
    if next_cursor:
        st.warning(
            "Sono disponibili ulteriori righe oltre quelle mostrate. "
            "Aumentare 'Righe per pagina' o restringere i filtri (date/scope). "
            "La navigazione per cursore sarà disponibile in una prossima release."
        )

    # Display columns
    display_cols = [
        c for c in [
            "emission_id", "superseded_by", "calc_timestamp",
            "valid_from", "valid_to", "created_by", "correlation_id",
            "reason_code", "scope", "sub_scope", "codice_sito", "anno",
            "tco2e", "gwp_set", "methodology", "factor_source", "factor_version",
            "regulatory_stream",
        ] if c in df.columns
    ]

    col_labels = {
        "emission_id": _("audit_emission_id", lang),
        "superseded_by": _("audit_predecessor", lang),
        "calc_timestamp": _("audit_timestamp", lang),
        "valid_from": _("audit_valid_from", lang),
        "valid_to": _("audit_valid_to", lang),
        "created_by": _("audit_user", lang),
        "correlation_id": _("audit_correlation", lang),
        "reason_code": _("audit_reason", lang),
        "scope": _("table_scope", lang),
        "sub_scope": _("table_sub_scope", lang),
        "codice_sito": _("table_site", lang),
        "anno": _("table_year", lang),
        "tco2e": _("table_tco2e", lang),
        "gwp_set": _("table_gwp_set", lang),
        "methodology": _("table_methodology", lang),
        "factor_source": _("table_factor_source", lang),
        "factor_version": _("table_factor_version", lang),
    }

    st.dataframe(
        df[display_cols].rename(columns=col_labels),
        use_container_width=True,
        hide_index=True,
    )

    # Emission detail modal (selectbox + caption — Streamlit doesn't have true modals)
    if "emission_id" in df.columns:
        emission_ids = df["emission_id"].dropna().astype(str).unique().tolist()
        selected_id = st.selectbox(
            "Dettaglio emission_id", [""] + emission_ids,
            help=_help("audit_predecessor", lang),
        )
        if selected_id:
            matches = df[df["emission_id"].astype(str) == selected_id]
            if not matches.empty:
                st.json(matches.iloc[0].to_dict())

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    f"{_('footer_factor_source', lang)} | {_('footer_methodology', lang)}"
)

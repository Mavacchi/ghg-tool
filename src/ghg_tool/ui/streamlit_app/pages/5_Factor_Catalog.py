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
    page_title=f"Factor Catalog · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.help import _help  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.brand import apply_brand_chrome, render_context_bar, render_role_chip  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.api_client import fetch_factor_catalog, publish_factor  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.exports import render_download_row  # noqa: E402

apply_brand_chrome()
require_auth()
lang = get_lang()

st.title(_("nav_factor_catalog", lang))

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
with st.sidebar:
    scope_opts = [_("all_label", lang), "1", "2", "3"]
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
        _("gwp_filter_label", lang), gwp_opts,
        help=_help("gwp", lang),
    )

    published_only = st.checkbox(
        "Solo pubblicati / Published only", value=True,
        help=_help("factor_version", lang),
    )

render_role_chip(st.session_state.get("role"), lang)

render_context_bar(
    lang=lang,
    year=None,
    gwp=gwp_filter or None,
    role=st.session_state.get("role"),
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

    _export_df = df[display_cols].rename(columns=col_labels)
    render_download_row(
        _export_df,
        basename=f"factor_catalog_{gwp_filter or 'all'}",
        lang=lang,
        key_prefix="fc",
    )
    st.dataframe(
        _export_df,
        use_container_width=True,
        hide_index=True,
    )

    st.caption(f"Totale fattori: {len(df)}")

# ---------------------------------------------------------------------------
# Publication queue (esg_manager only)
#
# Lists draft factors (is_published=False) and exposes a single-click
# publish action wired to POST /api/v1/factor-catalog/{id}/publish.
# Once published, the DB trigger MG-02 freezes the row.
# ---------------------------------------------------------------------------
_REASON_CODES = (
    "INITIAL_PUBLICATION",
    "VERSION_BUMP",
    "METHODOLOGY_UPDATE",
    "SOURCE_REVISION",
    "CORRECTION_REPLACEMENT",
)

_role = st.session_state.get("role", "auditor")
if _role == "esg_manager":
    with st.expander(_("publication_queue_title", lang), expanded=False):
        st.caption(_("publication_queue_caption", lang))
        # Filter the already-fetched catalog down to publishable drafts:
        # not yet published, not TBC, value set OR licence-only marked.
        # This mirrors the server-side 422 pre-conditions exactly.
        all_factors = raw or []
        drafts = [
            f for f in all_factors
            if not f.get("is_published") and not f.get("is_tbc")
            and (f.get("value") is not None or f.get("is_licence_only"))
        ]
        if not drafts:
            st.info(_("publication_queue_empty", lang))
        else:
            for d in drafts:
                _key = f"publish_{d.get('id')}"
                with st.container(border=True):
                    head = st.columns([3, 1])
                    with head[0]:
                        st.markdown(
                            f"**{d.get('factor_id', '?')}** · v{d.get('version', '?')} "
                            f"· {d.get('source', '?')} · {d.get('gwp_set', '?')}"
                        )
                        if d.get("substance"):
                            st.caption(f"{d.get('substance')} ({d.get('unit', '')})")
                    with head[1]:
                        val = d.get("value")
                        st.markdown(
                            f"`{val}`" if val is not None
                            else f"_{_('licence_only_label', lang)}_"
                        )

                    reason_code = st.selectbox(
                        _("publish_reason_label", lang),
                        _REASON_CODES,
                        index=None,
                        key=f"reason_{_key}",
                        format_func=lambda c: _(f"publish_reason_{c}", lang),
                    )
                    notes = st.text_area(
                        _("publish_notes_label", lang),
                        key=f"notes_{_key}",
                        max_chars=2000,
                        placeholder=_("publish_notes_placeholder", lang),
                    )
                    _inflight = st.session_state.get(f"_inflight_{_key}", False)
                    if st.button(
                        _("publish_btn", lang),
                        key=_key,
                        type="primary",
                        disabled=_inflight or reason_code is None,
                    ):
                        st.session_state[f"_inflight_{_key}"] = True
                        try:
                            resp = publish_factor(
                                str(d.get("id")),
                                reason_code=reason_code,
                                notes=notes or None,
                            )
                        finally:
                            st.session_state[f"_inflight_{_key}"] = False
                        if "error" in resp:
                            sc = resp.get("status_code")
                            if sc == 409:
                                st.warning(_("publish_already_done", lang))
                            elif sc == 422:
                                st.error(_("publish_validation_failed", lang))
                            elif sc == 403:
                                st.error(_("publish_forbidden", lang))
                            else:
                                st.error(f"HTTP {sc}: {resp.get('error', '?')}")
                        else:
                            st.success(_("publish_success", lang))
                            # Invalidate the catalog cache so the next
                            # render hides the just-published draft.
                            clear = getattr(fetch_factor_catalog, "clear", None)
                            if callable(clear):
                                try:
                                    clear()
                                except (AttributeError, TypeError):
                                    pass

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    f"{_('footer_gwp_set', lang)}: {gwp_filter or _('all_label', lang)} | "
    f"{_('footer_factor_source', lang)} | "
    f"{_('footer_methodology', lang)}"
)

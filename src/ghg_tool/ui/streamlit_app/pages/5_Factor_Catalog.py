"""Factor Catalog browser + CRUD page (FR-04, FR-29).

Read-only browsable table over the factor catalog for all authenticated users.
data_steward role additionally gets:
  - Inline edit form (st.expander) for DRAFT factors.
  - Two-step delete confirmation for DRAFT factors.
  - Lock badge + tooltip on PUBLISHED factors (immutable per ADR-007).

esg_manager role also gets the Publication Queue (unchanged from prior version).

Filters: regulatory_stream, gwp_set, source, scope, effective_from range.
"""

from __future__ import annotations

import datetime

import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    DASHBOARD_ID, DASHBOARD_VERSION, PRODUCT_NAME, page_icon,
)

st.set_page_config(
    page_title=f"Factor Catalog · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

from ghg_tool.ui.streamlit_app.lib.auth import get_lang, get_token, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.help import _help  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.brand import apply_brand_chrome, render_context_bar, render_role_chip  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.api_client import (  # noqa: E402
    fetch_factor_catalog,
    publish_factor,
    patch_factor_draft,
    delete_factor_draft,
    FactorCRUDError,
)
from ghg_tool.ui.streamlit_app.lib.exports import render_download_row  # noqa: E402

import pandas as pd  # noqa: E402

apply_brand_chrome()
require_auth()
lang = get_lang()

_role = st.session_state.get("role", "viewer")
_token = get_token() or ""

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
# ---------------------------------------------------------------------------
_REASON_CODES = (
    "INITIAL_PUBLICATION",
    "VERSION_BUMP",
    "METHODOLOGY_UPDATE",
    "SOURCE_REVISION",
    "CORRECTION_REPLACEMENT",
)

if _role == "admin":
    with st.expander(_("publication_queue_title", lang), expanded=False):
        st.caption(_("publication_queue_caption", lang))
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
                            clear = getattr(fetch_factor_catalog, "clear", None)
                            if callable(clear):
                                try:
                                    clear()
                                except (AttributeError, TypeError):
                                    pass

# ---------------------------------------------------------------------------
# CRUD affordances — data_steward only
#
# For each factor, the steward sees:
#   - DRAFT row: "Modifica bozza" expander + "Elimina bozza" two-step button.
#   - PUBLISHED row: lock badge + tooltip (no edit/delete affordances).
#
# The read-only fallback (auditor, esg_manager) hides ALL action buttons
# entirely — greyed-out buttons are noise for roles that cannot act.
# ---------------------------------------------------------------------------
if _role == "editor" and raw:
    all_factors_for_crud = raw

    # Partition into drafts vs published for clear UX
    draft_factors = [f for f in all_factors_for_crud if not f.get("is_published")]
    published_factors = [f for f in all_factors_for_crud if f.get("is_published")]

    st.divider()
    st.markdown("### Gestione bozze / Draft management")

    # ---- Empty state ---------------------------------------------------
    if not draft_factors:
        # safe: static markup + i18n strings, no user/db data
        st.markdown(
            """
<div class="ct-empty-state">
  <div class="ct-empty-icon">&#128196;</div>
  <p class="ct-empty-title">"""
            + _("empty_state_drafts", lang)
            + """</p>
  <p class="ct-empty-body">Vai a <em>Inserimento dati</em> per creare il primo fattore in bozza.</p>
</div>
""",
            unsafe_allow_html=True,
        )
    else:
        st.caption(f"{len(draft_factors)} bozze disponibili per la modifica.")

        for factor in draft_factors:
            _fid = str(factor.get("id", ""))
            _flabel = (
                f"**{factor.get('factor_id', '?')}** "
                f"· v{factor.get('version', '?')} "
                f"· {factor.get('source', '?')}"
            )

            with st.container(border=True):
                _hcols = st.columns([5, 1, 1])
                with _hcols[0]:
                    st.markdown(_flabel)
                    if factor.get("substance"):
                        st.caption(
                            f"{factor.get('substance')} · "
                            f"{factor.get('unit', '')} · "
                            f"GWP {factor.get('gwp_set', '')}"
                        )

                # ---- Edit expander ----------------------------------------
                _edit_key = f"edit_open_{_fid}"
                with _hcols[1]:
                    if st.button(
                        "✎ " + _("factor_edit_btn", lang),
                        key=f"edit_btn_{_fid}",
                        help=_("factor_edit_btn", lang),
                    ):
                        # Toggle the edit panel open/closed
                        st.session_state[_edit_key] = not st.session_state.get(_edit_key, False)

                # ---- Delete button (two-step) ------------------------------
                _del_confirm_key = f"del_confirm_{_fid}"
                with _hcols[2]:
                    # safe: static markup, no user/db data
                    st.markdown(
                        '<div class="ct-destructive-wrap"></div>',
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        "✕ " + _("factor_delete_btn", lang),
                        key=f"del_btn_{_fid}",
                        help=_("factor_delete_btn", lang),
                    ):
                        # Toggle confirmation state
                        st.session_state[_del_confirm_key] = not st.session_state.get(
                            _del_confirm_key, False
                        )

                # ---- Delete confirmation (two-step UX) --------------------
                if st.session_state.get(_del_confirm_key, False):
                    st.warning(_("factor_delete_confirm", lang))
                    _dc1, _dc2, _dc_spacer = st.columns([1, 1, 4])
                    _do_rerun_after_delete = False
                    with _dc1:
                        if st.button(
                            "Si, elimina",
                            key=f"del_yes_{_fid}",
                            type="primary",
                        ):
                            _delete_error: str | None = None
                            with st.spinner("Eliminazione in corso..."):
                                try:
                                    delete_factor_draft(_fid, token=_token)
                                    st.session_state[_del_confirm_key] = False
                                    _clear = getattr(fetch_factor_catalog, "clear", None)
                                    if callable(_clear):
                                        try:
                                            _clear()
                                        except (AttributeError, TypeError):
                                            pass
                                    _do_rerun_after_delete = True
                                except FactorCRUDError as exc:
                                    _delete_error = (
                                        f"Eliminazione fallita (HTTP {exc.status_code}): "
                                        f"{exc.detail}"
                                    )
                                    st.session_state[_del_confirm_key] = False
                            # st.rerun() and st.toast() are called OUTSIDE the spinner
                            # context to avoid Streamlit RerunException inside a context
                            # manager, which suppresses the rerun in some Streamlit builds.
                            if _delete_error:
                                st.error(_delete_error)
                            elif _do_rerun_after_delete:
                                st.toast(_("toast_factor_deleted", lang), icon="✓")
                                st.rerun()
                    with _dc2:
                        if st.button("No, annulla", key=f"del_no_{_fid}"):
                            st.session_state[_del_confirm_key] = False
                            st.rerun()

                # ---- Inline edit form (toggled by edit button) ------------
                if st.session_state.get(_edit_key, False):
                    # safe: static markup, no user/db data
                    st.markdown(
                        '<div class="ct-edit-panel">',
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"**{_('factor_edit_btn', lang)}** — {factor.get('factor_id', '')}")

                    with st.form(key=f"edit_form_{_fid}"):
                        _ecol1, _ecol2 = st.columns(2)

                        with _ecol1:
                            new_value = st.number_input(
                                "Valore / Value",
                                value=float(factor.get("value") or 0.0),
                                min_value=0.0,
                                step=0.000001,
                                format="%.6f",
                                key=f"ef_value_{_fid}",
                            )
                            new_unit = st.text_input(
                                "Unità / Unit",
                                value=str(factor.get("unit") or ""),
                                key=f"ef_unit_{_fid}",
                            )
                            new_vintage = st.text_input(
                                "Vintage",
                                value=str(factor.get("vintage") or ""),
                                key=f"ef_vintage_{_fid}",
                                help="Es. 2024, 2023-2024",
                            )
                            new_is_licence_only = st.toggle(
                                "Licence-only",
                                value=bool(factor.get("is_licence_only", False)),
                                key=f"ef_licence_{_fid}",
                            )

                        with _ecol2:
                            new_biogenic = st.number_input(
                                "CO2 Biogenico (kg/unità)",
                                value=float(factor.get("biogenic_co2_kg_per_unit") or 0.0),
                                min_value=0.0,
                                step=0.000001,
                                format="%.6f",
                                key=f"ef_biogenic_{_fid}",
                            )
                            _vf_raw = factor.get("valid_from")
                            _vf_default: datetime.date | None = None
                            if _vf_raw:
                                try:
                                    _vf_default = datetime.date.fromisoformat(str(_vf_raw)[:10])
                                except (ValueError, TypeError):
                                    _vf_default = None
                            new_valid_from = st.date_input(
                                _("factor_effective_from", lang),
                                value=_vf_default,
                                key=f"ef_valid_from_{_fid}",
                            )
                            new_pdf_uri = st.text_input(
                                _("factor_uri", lang),
                                value=str(factor.get("pdf_source_uri") or ""),
                                key=f"ef_pdf_{_fid}",
                                placeholder="https://...",
                            )

                        new_note = st.text_area(
                            "Note di applicabilità / Applicability note",
                            value=str(factor.get("applicability_note") or ""),
                            key=f"ef_note_{_fid}",
                            max_chars=2000,
                            height=90,
                        )

                        _fcol_save, _fcol_cancel = st.columns([1, 1])
                        with _fcol_save:
                            _submitted = st.form_submit_button(
                                _("factor_save_btn", lang),
                                type="primary",
                                use_container_width=True,
                            )
                        with _fcol_cancel:
                            _cancelled = st.form_submit_button(
                                "Annulla / Cancel",
                                use_container_width=True,
                            )

                        if _submitted:
                            _updates: dict[str, object] = {
                                "value": new_value,
                                "unit": new_unit,
                                "applicability_note": new_note,
                                "pdf_source_uri": new_pdf_uri or None,
                                "biogenic_co2_kg_per_unit": new_biogenic if new_biogenic > 0 else None,
                                "is_licence_only": new_is_licence_only,
                                "vintage": new_vintage or None,
                                "valid_from": new_valid_from.isoformat() if new_valid_from else None,
                            }
                            with st.spinner("Salvataggio in corso..."):
                                try:
                                    patch_factor_draft(_fid, _updates, token=_token)
                                    st.session_state[_edit_key] = False
                                    _clear = getattr(fetch_factor_catalog, "clear", None)
                                    if callable(_clear):
                                        try:
                                            _clear()
                                        except (AttributeError, TypeError):
                                            pass
                                    st.toast(_("toast_factor_saved", lang), icon="✓")
                                    st.rerun()
                                except FactorCRUDError as exc:
                                    st.error(
                                        f"Errore salvataggio (HTTP {exc.status_code}): {exc.detail}"
                                    )

                        if _cancelled:
                            st.session_state[_edit_key] = False
                            st.rerun()

                    # safe: static closing tag, no user/db data
                    st.markdown("</div>", unsafe_allow_html=True)

    # ---- Published factors: lock badge only (no affordances) ---------------
    if published_factors:
        st.markdown("#### Fattori pubblicati / Published factors")
        st.caption(
            f"{len(published_factors)} fattori pubblicati — immutabili per ADR-007 / ISAE 3000."
        )
        for pub in published_factors:
            with st.container(border=True):
                _pcols = st.columns([5, 1])
                with _pcols[0]:
                    st.markdown(
                        f"**{pub.get('factor_id', '?')}** "
                        f"· v{pub.get('version', '?')} "
                        f"· {pub.get('source', '?')}"
                    )
                    if pub.get("substance"):
                        st.caption(
                            f"{pub.get('substance')} · {pub.get('unit', '')} · "
                            f"GWP {pub.get('gwp_set', '')}"
                        )
                with _pcols[1]:
                    # safe: only static i18n string in attribute (no user/db data)
                    st.markdown(
                        f'<span class="ct-lock-badge" title="{_("factor_locked_tooltip", lang)}">'
                        f"&#128274; Pubblicato</span>",
                        unsafe_allow_html=True,
                    )

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

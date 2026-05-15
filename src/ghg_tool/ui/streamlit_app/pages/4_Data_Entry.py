"""Data Entry page (FR-21) - new emissions, corrections, new factors.

Carbontrace is an append-only ledger. There is no UPDATE / DELETE on
``calc.emissions_consolidated`` (DB trigger ``trg_emissions_deny_mutation``).
Corrections create a new row pointing to the predecessor via
``superseded_by``; published factors are frozen by MG-02.

This page exposes three flows backed by existing API endpoints:

  1. ``Tab 1 - Nuova emissione``: POST /api/v1/emissions/
     Pick a factor from the catalog (it pre-fills factor_version,
     factor_source, gwp_set, methodology).
  2. ``Tab 2 - Correggi / revoca``: POST /api/v1/emissions/correction
     Search -> select -> form (pre-filled from the supersedee) ->
     mandatory reason_code + min-10-char justification. A "Revoca"
     preset zeroes tco2e with reason_code=DATA_ERROR.
  3. ``Tab 3 - Nuovo fattore``: POST /api/v1/factor-catalog/
     Always pre-publish (is_published forced False client-side).

Demo mode: writes are still attempted, but the API will reject the
demo JWT with 401 on protected POST routes. A persistent banner makes
this explicit so users don't think the operation succeeded silently.
"""

from __future__ import annotations

import datetime as dt
import json

import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    DASHBOARD_ID, DASHBOARD_VERSION, KNOWN_SITES, PRODUCT_NAME, page_icon,
)

st.set_page_config(
    page_title=f"Inserimento dati · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

from ghg_tool.ui.streamlit_app.lib.auth import (  # noqa: E402
    get_lang, is_demo_mode, require_auth,
)
from ghg_tool.ui.streamlit_app.lib.brand import apply_brand_chrome, render_context_bar, render_role_chip  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.help import _help  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.api_client import (  # noqa: E402
    create_emission,
    create_factor,
    fetch_emissions,
    fetch_factor_catalog,
    import_excel,
    post_correction,
)

apply_brand_chrome()
require_auth()
lang = get_lang()

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
st.title(_("nav_data_entry", lang))

render_role_chip(st.session_state.get("role"), lang)

render_context_bar(
    lang=lang,
    year=None,
    gwp=None,
    role=st.session_state.get("role"),
)


# Append-only explainer (the most important message on this page).
st.info(
    "Carbontrace è un registro **append-only** conforme ISAE 3000. "
    "I dati storici non si modificano: si correggono creando una nuova "
    "versione tracciata. Nessuna riga viene mai cancellata.",
    icon="🔒",
)

# Role + demo banners.
role = st.session_state.get("role", "auditor")
if is_demo_mode():
    st.warning(
        "**Modalità DEMO attiva.** Le operazioni di scrittura verranno rifiutate dall'API "
        "con HTTP 401: il token demo non ha i privilegi necessari. Per esercitarsi, "
        "usa pure il form e leggi il payload anteprima, ma non aspettarti che la riga "
        "compaia in Audit Trail.",
        icon="⚠️",
    )
elif role == "auditor":
    st.warning(
        "Il tuo ruolo (`auditor`) è di sola lettura. Nessuna operazione di scrittura è abilitata.",
        icon="🔒",
    )

# ---------------------------------------------------------------------------
# Reusable helpers
# ---------------------------------------------------------------------------

_REASON_CODES_FRIENDLY = {
    "DATA_ERROR": "Errore di inserimento dati",
    "FACTOR_UPDATE": "Aggiornamento fattore di emissione",
    "BOUNDARY_CHANGE": "Variazione perimetro di consolidamento",
    "METHODOLOGY_REVISION": "Revisione metodologica",
    "RESTATEMENT_>5PCT": "Restatement (impatto > 5%)",
}

_FACTOR_SOURCES = [
    "DEFRA", "ISPRA", "IEA", "ecoinvent", "EXIOBASE",
    "CDP", "IPCC", "AIB", "EPD", "GHGProtocol",
]

_METHODOLOGIES = [
    "activity-based", "mass-based", "spend-based",
    "distance-based", "stoichiometric", "declared-zero",
    "location-based", "market-based",
]

# Canonical sub-scope vocabulary, mirroring domain.entities.emission_record.
_SUB_SCOPES_BY_SCOPE: dict[int, list[str]] = {
    1: ["combustion", "process", "fugitive", "biogenic"],
    2: ["LB", "MB"],
    3: [f"Cat{n}" for n in (1, 2, 3, 4, 5, 6, 7, 9, 11, 12)],
}


def _explain_api_error(resp: dict) -> str:
    """Render an API error dict as a user-facing message in IT."""
    sc = resp.get("status_code")
    err = resp.get("error", "errore sconosciuto")
    if sc == 401:
        return "Sessione scaduta o token non valido. Effettua di nuovo l'accesso."
    if sc == 403:
        return f"Il tuo ruolo (`{role}`) non può eseguire questa operazione."
    if sc == 422:
        return f"Dati non validi: {err}"
    if sc == 409:
        return "Conflitto: la riga è stata già corretta da un altro utente. Ricarica e riprova."
    if sc:
        return f"Errore HTTP {sc}: {err}"
    return f"Errore di rete: {err}"


def _show_success(label: str, payload: dict) -> None:
    """Render a uniform success block with the response payload.

    Invalidates the read-side caches so the new row is visible on the
    Audit Trail / Drill-down pages immediately, not after the 5 min
    TTL configured on ``@st.cache_data`` wrappers in ``api_client.py``.

    The "Open Audit Trail" CTA uses ``st.page_link`` so the user moves
    to the audit page in one click rather than having to spot the
    sidebar entry.
    """
    st.success(f"{label} eseguita.", icon="✅")
    new_id = payload.get("id") or payload.get("new_id")
    if new_id:
        st.caption("ID nuova riga")
        st.code(str(new_id), language="text")
    supersedes_id = payload.get("supersedes_id")
    if supersedes_id:
        st.caption(f"Predecessore chiuso: `{supersedes_id}`")
    corr = payload.get("correlation_id")
    if corr:
        st.caption(f"Correlation ID: `{corr}`")

    # Invalidate any cached GETs that just went stale. clear() can raise
    # AttributeError if the underlying cache wrapper has been swapped at
    # runtime (e.g. in tests); a TypeError surfaces when the wrapper does
    # not actually carry a callable. Both are recoverable - cache
    # invalidation is best-effort and never blocks the write success path.
    for fn in (fetch_emissions, fetch_factor_catalog):
        clear = getattr(fn, "clear", None)
        if callable(clear):
            try:
                clear()
            except (AttributeError, TypeError):
                pass

    # Primary CTA: one-click jump to Audit Trail to verify the new row.
    if hasattr(st, "page_link"):
        st.page_link(
            "pages/7_Audit_Trail.py",
            label=_("view_in_audit_trail", lang),
            icon="🔍",
        )


def _submit_once(key: str) -> bool:
    """Single-shot submit guard. Returns True only on the first call per token.

    Streamlit reruns the whole script on every widget interaction; an inner
    confirmation button placed inside an expander can re-fire during latency
    and produce duplicate POSTs. Storing the inflight token in session_state
    forces idempotency on the client side. The server-side append-only
    guarantees do NOT prevent semantic duplicates — they only prevent
    UPDATE/DELETE — so this guard is necessary for ledger hygiene.
    """
    state_key = f"_inflight_{key}"
    if st.session_state.get(state_key):
        return False
    st.session_state[state_key] = True
    return True


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_new, tab_correct, tab_factor, tab_excel = st.tabs(
    [
        "➕ Nuova emissione",
        "✎ Correggi o revoca riga",
        "📑 Nuovo fattore",
        "📂 Importa Excel",
    ]
)

# ===========================================================================
# Tab 1 - New emission
# ===========================================================================
with tab_new:
    st.subheader("Nuova emissione")
    st.caption(
        "Inserisce una riga nuova nel registro consolidato. "
        "Richiede ruolo `data_steward` o `esg_manager`."
    )

    # Load factor catalog up-front so the picker has options.
    factors_raw = fetch_factor_catalog(limit=200) or []
    factors_published = [
        f for f in factors_raw if f.get("is_published", False)
    ]
    factor_labels = [
        f"{f.get('source', '?')} · {f.get('factor_id', '?')} · v{f.get('version', '?')} ({f.get('gwp_set', '?')})"
        for f in factors_published
    ]

    with st.form("new_emission_form", clear_on_submit=False):
        col_a, col_b = st.columns(2)
        with col_a:
            scope = st.radio(
                "Scope", [1, 2, 3], horizontal=True,
                help=_help("scope1", lang),
            )
            sub_scope = st.selectbox(
                "Sub-scope",
                _SUB_SCOPES_BY_SCOPE.get(int(scope), []),
            )
            codice_sito = st.selectbox(
                "Codice sito",
                list(KNOWN_SITES),
                help=_help("codice_sito", lang),
            )
            anno = st.number_input(
                "Anno fiscale",
                min_value=2020, max_value=dt.date.today().year + 1,
                value=dt.date.today().year - 1, step=1,
                help=_help("anno_fiscale", lang),
            )
        with col_b:
            tco2e = st.number_input(
                "tCO2e", min_value=0.0, value=0.0, step=0.001, format="%.6f",
                help=_help("tco2e", lang),
            )
            regulatory_stream = st.selectbox(
                "Regulatory stream",
                ["CSRD_ESRS_E1", "EU_ETS_PHASE_IV"],
                help=_help("esrs_e1", lang),
            )
            methodology = st.selectbox(
                "Metodologia",
                _METHODOLOGIES,
                help=_help("methodology", lang),
            )

        st.markdown("**Fattore di emissione**")
        if not factor_labels:
            st.error(
                "Nessun fattore pubblicato disponibile. Crea prima un fattore "
                "(tab successiva) e pubblicalo, poi torna qui."
            )
            factor_pick_idx: int | None = None
        else:
            factor_pick_idx = st.selectbox(
                "Seleziona il fattore",
                range(len(factor_labels)),
                format_func=lambda i: factor_labels[i],
                help=_help("factor_source", lang),
            )

        disclosure_notes = st.text_area(
            "Note di disclosure (opzionali)",
            max_chars=2000,
            placeholder="Es. Calcolo per chiusura bilancio Q4 2025…",
        )

        submitted = st.form_submit_button(
            "Verifica e invia", type="primary",
            disabled=factor_pick_idx is None,
        )

    if submitted and factor_pick_idx is not None:
        picked = factors_published[factor_pick_idx]
        payload = {
            "scope": int(scope),
            "sub_scope": sub_scope,
            "codice_sito": codice_sito,
            "anno": int(anno),
            "tco2e": float(tco2e),
            "factor_id": picked.get("id"),
            "factor_version": picked.get("version"),
            "factor_source": picked.get("source"),
            "gwp_set": picked.get("gwp_set"),
            "methodology": methodology,
            "regulatory_stream": regulatory_stream,
            "raw_scope": int(scope),
            "disclosure_notes": disclosure_notes or None,
        }

        with st.expander("Verifica payload prima dell'invio", expanded=True):
            st.code(json.dumps(payload, indent=2, default=str), language="json")
            confirm = st.button(
                "Conferma e invia al registro", type="primary",
                key="confirm_new_emission",
                disabled=st.session_state.get("_inflight_new_emission", False),
            )
            if confirm and _submit_once("new_emission"):
                try:
                    resp = create_emission(payload)
                finally:
                    st.session_state["_inflight_new_emission"] = False
                if "error" in resp:
                    st.error(_explain_api_error(resp))
                else:
                    _show_success("Inserimento", resp)

# ===========================================================================
# Tab 2 - Correction / revocation
# ===========================================================================
with tab_correct:
    st.subheader("Correggi o revoca riga esistente")
    st.caption(
        "La correzione crea una NUOVA riga con un nuovo UUID e chiude la "
        "precedente. Entrambe restano consultabili in Audit Trail."
    )

    # Step 1: search
    with st.container(border=True):
        st.markdown("**1. Cerca la riga da correggere**")
        s_col1, s_col2, s_col3, _s_col4 = st.columns([1, 1, 1, 1])
        with s_col1:
            f_anno = st.number_input(
                "Anno", min_value=2020, max_value=dt.date.today().year + 1,
                value=dt.date.today().year - 1, step=1, key="corr_anno",
            )
        _all = _("all_label", lang)
        with s_col2:
            f_site = st.selectbox(
                "Sito", [_all] + list(KNOWN_SITES), key="corr_site",
            )
        with s_col3:
            f_scope = st.selectbox(
                "Scope", [_all, 1, 2, 3], key="corr_scope",
            )

        if st.button(_("search_btn", lang), key="search_emissions_btn"):
            raw = fetch_emissions(
                anno=int(f_anno),
                codice_sito=None if f_site == _all else f_site,
                scope=None if f_scope == _all else int(f_scope),
                limit=50,
            )
            # The endpoint normally returns a list. If the wrapper hit an
            # error it returns a dict with an "error" key; surface it.
            if isinstance(raw, dict) and "error" in raw:
                st.error(_explain_api_error(raw))
                rows = []
            else:
                rows = raw if isinstance(raw, list) else []
            # Cache the search result in session_state so the rest of the
            # form survives subsequent reruns triggered by widget changes.
            st.session_state["correction_results"] = rows

    rows = st.session_state.get("correction_results", [])
    if not rows:
        st.caption("Nessuna ricerca eseguita o nessun risultato.")
    else:
        st.markdown(f"**Trovate {len(rows)} righe.** Seleziona quella da correggere.")
        labels = [
            f"#{i + 1} · {r.get('codice_sito', '?')} · "
            f"Scope {r.get('scope')} ({r.get('sub_scope', '?')}) · "
            f"{r.get('anno')} · {r.get('tco2e', 0):.3f} tCO2e"
            for i, r in enumerate(rows)
        ]
        pick = st.selectbox(
            "Riga selezionata", range(len(rows)),
            format_func=lambda i: labels[i],
        )
        selected_row = rows[int(pick)] if rows else None

        if selected_row is not None:
            st.markdown("**2. Riga corrente (sola lettura)**")
            curr_a, curr_b = st.columns(2)
            with curr_a:
                st.caption("ID")
                st.code(selected_row.get("id", ""), language="text")
                st.caption(f"Sito: `{selected_row.get('codice_sito')}`")
                st.caption(f"Anno: `{selected_row.get('anno')}`")
                st.caption(f"Scope: `{selected_row.get('scope')}`")
            with curr_b:
                st.metric("tCO2e attuale", f"{selected_row.get('tco2e', 0):.3f}")
                st.caption(f"Sub-scope: `{selected_row.get('sub_scope')}`")
                st.caption(f"Fattore: `{selected_row.get('factor_source')}` v{selected_row.get('factor_version')}")

            revoke_mode = st.toggle(
                "Revoca riga (azzera valore)",
                help=(
                    "Pre-compila tCO2e=0. Verrà comunque creata una nuova "
                    "riga; la riga originale NON viene cancellata. "
                    "Devi comunque scegliere il motivo di correzione coerente "
                    "(es. BOUNDARY_CHANGE per ritiri di perimetro, "
                    "RESTATEMENT_>5PCT per restatement materiali)."
                ),
            )

            st.markdown("**3. Nuovo valore**")
            new_tco2e = st.number_input(
                "Nuovo tCO2e",
                min_value=0.0,
                value=0.0 if revoke_mode else float(selected_row.get("tco2e", 0)),
                step=0.001, format="%.6f",
                disabled=revoke_mode,
            )

            st.markdown("**4. Motivazione**")
            # Always require an explicit reason_code pick. Auto-defaulting to
            # DATA_ERROR for revocations is not CSRD-defensible: a zero-out
            # is a withdrawal, not necessarily a data-entry error. ESRS 1
            # §85 restatement-disclosure expects the reason taxonomy to
            # reflect the actual cause.
            reason = st.selectbox(
                "Motivo correzione",
                list(_REASON_CODES_FRIENDLY.keys()),
                index=None,
                format_func=lambda c: f"{_REASON_CODES_FRIENDLY[c]} ({c})",
                placeholder="Seleziona il motivo…",
            )

            justification = st.text_area(
                "Giustificazione (min 10 caratteri)",
                placeholder="Es. Errata lettura del contatore gas naturale di gennaio; rilevato durante chiusura bilancio 2025.",
                max_chars=1000,
            )

            st.info(
                "Confermando, verrà creata una NUOVA riga con un nuovo UUID. "
                "La riga corrente verrà chiusa (`valid_to` valorizzato; "
                "`superseded_by` punterà alla nuova). Entrambe restano in "
                "archivio per audit ISAE 3000.",
                icon="🔗",
            )

            if st.button(
                "Verifica e applica correzione", type="primary",
                disabled=(len(justification.strip()) < 10 or reason is None),
            ):
                new_record = {
                    "scope": int(selected_row.get("scope")),
                    "sub_scope": selected_row.get("sub_scope"),
                    "codice_sito": selected_row.get("codice_sito"),
                    "anno": int(selected_row.get("anno")),
                    "tco2e": float(new_tco2e),
                    "factor_id": selected_row.get("factor_id"),
                    "factor_version": selected_row.get("factor_version"),
                    "factor_source": selected_row.get("factor_source"),
                    "gwp_set": selected_row.get("gwp_set"),
                    "methodology": selected_row.get("methodology"),
                    "regulatory_stream": selected_row.get("regulatory_stream", "CSRD_ESRS_E1"),
                    "raw_scope": int(selected_row.get("raw_scope", selected_row.get("scope"))),
                }

                with st.expander("Verifica payload prima dell'invio", expanded=True):
                    st.code(json.dumps({
                        "supersedes_id": selected_row.get("id"),
                        "new_record": new_record,
                        "reason_code": reason,
                        "justification": justification,
                    }, indent=2, default=str), language="json")
                    confirm_corr = st.button(
                        "Conferma e invia correzione", type="primary",
                        key="confirm_correction",
                        disabled=st.session_state.get("_inflight_correction", False),
                    )
                    if confirm_corr and _submit_once("correction"):
                        try:
                            resp = post_correction(
                                supersedes_id=str(selected_row.get("id")),
                                new_record=new_record,
                                reason_code=reason,
                                justification=justification,
                            )
                        finally:
                            st.session_state["_inflight_correction"] = False
                        if "error" in resp:
                            st.error(_explain_api_error(resp))
                        else:
                            _show_success("Correzione", resp)

# ===========================================================================
# Tab 3 - New factor (pre-publish)
# ===========================================================================
with tab_factor:
    st.subheader("Nuovo fattore di emissione")
    st.caption(
        "Crea una versione NON pubblicata. Una volta pubblicato, "
        "il fattore è immutabile (regola MG-02): per correggerlo "
        "serve registrare una nuova versione."
    )
    st.info(
        "**Stato pubblicazione.** Questa interfaccia crea fattori in stato "
        "*draft*: non sono utilizzabili in calcolo finché non vengono pubblicati. "
        "Il flusso di pubblicazione (che richiede approvazione `esg_manager` e "
        "registra timestamp + identità del pubblicatore per audit ISAE 3000) "
        "non è ancora disponibile in questa release: arriva con la wave 3.",
        icon="📌",
    )

    with st.form("new_factor_form", clear_on_submit=False):
        col_l, col_r = st.columns(2)
        with col_l:
            factor_id = st.text_input(
                "Identificatore fattore",
                placeholder="Es. WTT_GAS_NAT_DEFRA_2025",
                max_chars=80,
            )
            version = st.text_input(
                "Versione", placeholder="Es. 2025.1", max_chars=40,
            )
            substance = st.text_input(
                "Sostanza / materiale", placeholder="Es. Gas naturale",
                max_chars=100,
            )
            f_scope = st.radio("Scope", [1, 2, 3], horizontal=True)
            category = st.text_input(
                "Categoria", placeholder="Es. fuel_combustion",
                max_chars=40,
            )
            source = st.selectbox(
                "Fonte", _FACTOR_SOURCES,
                help=_help("factor_source", lang),
            )
        with col_r:
            value = st.number_input(
                "Valore fattore",
                min_value=0.0, value=0.0, step=0.0001, format="%.6f",
            )
            is_licence_only = st.checkbox(
                "Fattore licence-only (valore non ripubblicabile)",
                help="Spuntare se la licenza della fonte vieta la ripubblicazione del valore numerico.",
            )
            unit = st.text_input(
                "Unità di misura",
                placeholder="Es. kg CO2e / Sm³", max_chars=40,
            )
            f_gwp_set = st.selectbox("GWP set", ["AR6", "AR5", "n/a"])
            vintage = st.text_input(
                "Vintage", placeholder="Es. 2024", max_chars=40,
            )
            valid_from = st.date_input(
                "Valido dal",
                value=dt.date(dt.date.today().year, 1, 1),
            )

        applicability_note = st.text_area(
            "Note di applicabilità (opzionale)",
            max_chars=2000,
            placeholder="Es. valido per gas naturale di rete italiana, esclude GPL.",
        )

        f_submit = st.form_submit_button(
            "Verifica e crea fattore", type="primary",
        )

    if f_submit:
        f_payload = {
            "factor_id": factor_id,
            "version": version,
            "substance": substance,
            "scope": int(f_scope),
            "category": category,
            "source": source,
            "value": None if is_licence_only else float(value),
            "is_licence_only": bool(is_licence_only),
            "unit": unit,
            "gwp_set": f_gwp_set,
            "vintage": vintage or None,
            "valid_from": valid_from.isoformat(),
            "applicability_note": applicability_note or None,
        }
        with st.expander("Verifica payload prima dell'invio", expanded=True):
            st.code(json.dumps(f_payload, indent=2, default=str), language="json")
            confirm_f = st.button(
                "Conferma e crea fattore", type="primary",
                key="confirm_new_factor",
                disabled=st.session_state.get("_inflight_new_factor", False),
            )
            if confirm_f and _submit_once("new_factor"):
                try:
                    resp = create_factor(f_payload)
                finally:
                    st.session_state["_inflight_new_factor"] = False
                if "error" in resp:
                    st.error(_explain_api_error(resp))
                else:
                    _show_success("Creazione fattore", resp)

# ===========================================================================
# Tab 4 - Excel import (FR-03)
#
# Lets data_steward / esg_manager upload an .xlsx workbook with three
# sheets (Scope1 / Scope2 / Scope3) and run a dry-run preview + DQ-CRIT
# validation before any DB write. The actual INSERT path delegates to the
# existing seed-data orchestrator so we never bypass the append-only
# triggers or the DQ gates that block bad data.
# ===========================================================================
with tab_excel:
    st.subheader("Importa Excel")
    st.caption(
        "Carica un file .xlsx con uno o piu` sheet Scope1 / Scope2 / Scope3. "
        "Il sistema esegue prima una validazione (pandera + DQ-CRIT) e poi "
        "richiede conferma esplicita prima dell'inserimento."
    )

    if role not in ("data_steward", "esg_manager"):
        st.warning(
            "Il tuo ruolo non puo` importare dati. Richiedi l'accesso "
            "data_steward o esg_manager.",
            icon="🔒",
        )
    else:
        uploaded = st.file_uploader(
            "File Excel (.xlsx)",
            type=["xlsx"],
            key="excel_upload",
            help=(
                "Lo schema deve seguire le colonne canoniche italiane "
                "(Codice_Sito, Quantita, Unita, ...). Vedi data/raw/ per esempi."
            ),
        )

        if uploaded is not None:
            from ghg_tool.etl.readers.excel_reader import (  # noqa: PLC0415
                WorkbookParseError,
                parse_workbook,
                summarise_parsed,
            )

            raw_bytes = uploaded.getvalue()
            try:
                parsed = parse_workbook(raw_bytes)
            except WorkbookParseError as exc:
                st.error(f"Errore di parsing del workbook: {exc}")
                parsed = None  # type: ignore[assignment]

            if parsed:
                st.markdown("**Anteprima caricamento**")
                summary = summarise_parsed(parsed)

                cols = st.columns(len(summary))
                for col, (scope_key, stats) in zip(cols, summary.items(), strict=False):
                    with col:
                        st.metric(
                            label=scope_key.upper(),
                            value=f"{stats['rows']} righe",
                            help=(
                                f"{stats['years']} anni distinti, "
                                f"{stats['sites']} siti distinti"
                            ),
                        )

                for scope_key, df_preview in parsed.items():
                    with st.expander(
                        f"Anteprima {scope_key.upper()} ({len(df_preview)} righe)",
                        expanded=False,
                    ):
                        st.dataframe(
                            df_preview.head(20),
                            use_container_width=True,
                            hide_index=True,
                        )

                st.divider()
                st.markdown("**Conferma e importa nel registro**")
                st.info(
                    "Cliccando il pulsante qui sotto, le righe del workbook vengono "
                    "inviate all'API che esegue la validazione DQ-CRIT e, se tutto "
                    "passa, le inserisce in `raw.scope{1,2,3}_ingestions`. "
                    "L'operazione e` irreversibile ma tracciata in Audit Trail.",
                    icon="ℹ️",
                )

                confirm_import = st.button(
                    "Conferma e importa",
                    type="primary",
                    key="confirm_excel_import",
                    disabled=st.session_state.get("_inflight_excel_import", False),
                )

                if confirm_import and _submit_once("excel_import"):
                    try:
                        with st.spinner("Importazione in corso..."):
                            resp = import_excel(raw_bytes)
                    finally:
                        st.session_state["_inflight_excel_import"] = False

                    if "error" in resp:
                        sc = resp.get("status_code")
                        err_body = resp.get("error", {})
                        if sc == 422:
                            # Surface DQ-CRIT findings inline so the user
                            # understands what to fix before re-uploading.
                            blocked_findings = []
                            if isinstance(err_body, dict):
                                blocked_findings = err_body.get(
                                    "blocked_findings", []
                                )
                                detail_msg = err_body.get("detail", str(err_body))
                            else:
                                detail_msg = str(err_body)

                            st.error(
                                f"Importazione bloccata dalla validazione DQ-CRIT: "
                                f"{detail_msg}",
                                icon="🚫",
                            )
                            if blocked_findings:
                                st.markdown("**Finding bloccanti:**")
                                for bf in blocked_findings:
                                    st.warning(
                                        f"**{bf.get('rule_id', '?')}** "
                                        f"(Scope {bf.get('scope', '?')}, "
                                        f"sito `{bf.get('codice_sito', '?')}`, "
                                        f"anno {bf.get('anno', '?')}): "
                                        f"{bf.get('trigger_desc', '')}. "
                                        f"Azione consigliata: "
                                        f"{bf.get('recommended_action', '')}",
                                    )
                        else:
                            st.error(_explain_api_error(resp))
                    else:
                        batch_id = resp.get("batch_id", "")
                        st.success(
                            f"Importazione completata. Batch ID: `{batch_id}`",
                            icon="✅",
                        )
                        col_s1, col_s2, col_s3, col_dq = st.columns(4)
                        col_s1.metric("Scope 1 righe", resp.get("scope1_rows", 0))
                        col_s2.metric("Scope 2 righe", resp.get("scope2_rows", 0))
                        col_s3.metric("Scope 3 righe", resp.get("scope3_rows", 0))
                        col_dq.metric("DQ findings", resp.get("dq_findings", 0))

                        if hasattr(st, "page_link"):
                            st.page_link(
                                "pages/7_Audit_Trail.py",
                                label=_("view_in_audit_trail", lang),
                                icon="🔍",
                            )

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    "Registro append-only conforme ISAE 3000."
)

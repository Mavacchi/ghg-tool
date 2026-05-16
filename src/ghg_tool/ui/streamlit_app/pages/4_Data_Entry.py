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
from ghg_tool.ui.clients.sites_client import (  # noqa: E402
    SITE_TYPE_LABELS,
    Site,
    get_site,
    get_sites,
    get_sites_by_type,
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
    AutoCalcError,
    calc_insert,
    calc_preview,
    create_emission,
    create_factor,
    fetch_emissions,
    fetch_excel_template,
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
role = st.session_state.get("role", "viewer")
if is_demo_mode():
    st.warning(
        "**Modalità DEMO attiva.** Le operazioni di scrittura verranno rifiutate dall'API "
        "con HTTP 401: il token demo non ha i privilegi necessari. Per esercitarsi, "
        "usa pure il form e leggi il payload anteprima, ma non aspettarti che la riga "
        "compaia in Audit Trail.",
        icon="⚠️",
    )
elif role == "viewer":
    st.warning(
        "Il tuo ruolo (`viewer`) è di sola lettura. Nessuna operazione di scrittura è abilitata.",
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

tab_new, tab_correct, tab_factor, tab_excel, tab_autocalc = st.tabs(
    [
        "➕ Nuova emissione",
        "✎ Correggi o revoca riga",
        "📑 Nuovo fattore",
        "📂 Importa Excel",
        "⚡ " + _("auto_calc_tab_title", lang),
    ]
)

# ===========================================================================
# Tab 1 - New emission
# ===========================================================================
with tab_new:
    st.subheader("Nuova emissione")
    st.caption(
        "Inserisce una riga nuova nel registro consolidato. "
        "Richiede ruolo **editor** o **admin**."
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
            _corr_site_codes = [s.codice_sito for s in get_sites()]
            f_site = st.selectbox(
                "Sito", [_all] + _corr_site_codes, key="corr_site",
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
        "Il flusso di pubblicazione (che richiede approvazione `admin` e "
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

    if role not in ("editor", "admin"):
        st.warning(
            "Il tuo ruolo non puo` importare dati. Richiedi l'accesso "
            "editor o admin.",
            icon="🔒",
        )
    else:
        # --- Modello vuoto scaricabile ---
        st.markdown("**Modello Excel**")
        if lang == "en":
            st.caption(
                "Download the empty template, fill in your data, then upload it below."
            )
        else:
            st.caption(
                "Scarica il modello vuoto, compila i tuoi dati, poi caricalo qui sotto."
            )

        template_bytes = fetch_excel_template()
        st.download_button(
            label="Scarica modello Excel" if lang != "en" else "Download Excel template",
            data=template_bytes or b"",
            file_name="carbontrace_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            disabled=template_bytes is None,
            key="download_excel_template",
            help=(
                "Scarica il file .xlsx con le colonne corrette per ogni scope. "
                "Compilalo e caricalo qui sotto per importare i tuoi dati."
                if lang != "en"
                else "Download the .xlsx file with the correct columns for each scope. "
                "Fill it in and upload it below to import your data."
            ),
        )

        st.divider()

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

# ===========================================================================
# Tab 5 - Auto-calc (feature-template-and-autocalc wave)
#
# Flow:
#   1. User picks Scope + sub-scope → conditional fields appear.
#   2. User fills quantity, unit, site, year, GWP, optional note.
#   3. "Calcola anteprima" → POST /api/v1/calc/preview (no DB write).
#   4. Preview card shows tCO2e metric + breakdown + formula + factor card.
#   5. "Conferma e registra" (enabled only after successful preview) →
#      POST /api/v1/calc/insert → success toast + reset + history entry.
#
# Scope 1 combustion : 3 fuels × 2+ modes = 6 paths
# Scope 1 process    : 2 input modes (direct tCO2 default, CaCO3 mass)
# Scope 2 LB        : 1 path
# Scope 2 MB        : 1 path (with strumento_mb selector)
# Scope 3 Cat 1,3,4,5,6,7,9,12 : 8 categories, generic quantity × factor
# Total: 13 sub-scope paths covered.
#
# Anomaly check: if quantita > 10× the category's "typical max" we show
# a confirmation dialog before insert to catch data-entry errors.
# ===========================================================================

# ---------------------------------------------------------------------------
# Auto-calc constants (vocabulary mirrors §10 API contract)
# ---------------------------------------------------------------------------

_AC_SCOPE_OPTIONS: list[int] = [1, 2, 3]

_AC_SUBSCOPE_LABELS: dict[str, str] = {
    # Scope 1
    "combustion_GAS_NAT":   "S1 Combustione — Gas Naturale",
    "combustion_GASOLIO":   "S1 Combustione — Gasolio Auto",
    "combustion_BENZINA":   "S1 Combustione — Benzina Auto",
    "process_direct":       "S1 Processo — Inserimento diretto tCO2",
    "process_caco3":        "S1 Processo — Massa CaCO3 (stoichiometrico)",
    # Scope 2
    "LB":                   "S2 Elettricita Location-Based",
    "MB":                   "S2 Elettricita Market-Based",
    # Scope 3
    "Cat1":                 "S3 Cat 1 — Purchased goods/services",
    "Cat3":                 "S3 Cat 3 — Fuel & Energy WTT/T&D",
    "Cat4":                 "S3 Cat 4 — Upstream transport",
    "Cat5":                 "S3 Cat 5 — Waste",
    "Cat6":                 "S3 Cat 6 — Business travel",
    "Cat7":                 "S3 Cat 7 — Commuting",
    "Cat9":                 "S3 Cat 9 — Downstream transport",
    "Cat12":                "S3 Cat 12 — End-of-life",
}

_AC_SUBSCOPE_BY_SCOPE: dict[int, list[str]] = {
    1: ["combustion_GAS_NAT", "combustion_GASOLIO", "combustion_BENZINA",
        "process_direct", "process_caco3"],
    2: ["LB", "MB"],
    3: ["Cat1", "Cat3", "Cat4", "Cat5", "Cat6", "Cat7", "Cat9", "Cat12"],
}

# Units per sub-scope key (shown in the unit selectbox)
_AC_UNITS: dict[str, list[str]] = {
    "combustion_GAS_NAT":   ["Sm3", "kWh", "MWh"],
    "combustion_GASOLIO":   ["litri", "kg", "t"],
    "combustion_BENZINA":   ["litri", "kg", "t"],
    "process_direct":       ["tCO2"],   # read-only
    "process_caco3":        ["kg", "t"],
    "LB":                   ["kWh", "MWh", "MJ"],
    "MB":                   ["kWh", "MWh", "MJ"],
    "Cat1":                 ["t", "EUR", "kg"],
    "Cat3":                 ["Sm3", "kWh", "MWh", "t"],
    "Cat4":                 ["t·km", "km", "t"],
    "Cat5":                 ["t", "kg"],
    "Cat6":                 ["km", "EUR", "night"],
    "Cat7":                 ["km", "person·km"],
    "Cat9":                 ["t·km", "km"],
    "Cat12":                ["t", "kg"],
}

# Typical "anomaly" ceiling per sub-scope (units as in _AC_UNITS first element).
# If quantita > ceiling → show anomaly warning dialog before insert.
_AC_ANOMALY_CEIL: dict[str, float] = {
    "combustion_GAS_NAT": 100_000_000,   # 100 M Sm3
    "combustion_GASOLIO": 1_000_000,     # 1 M litri
    "combustion_BENZINA": 1_000_000,
    "process_direct":      100_000,      # 100 k tCO2
    "process_caco3":       500_000_000,  # 500 k t CaCO3 (kg)
    "LB":                  1_000_000_000, # 1 TWh
    "MB":                  1_000_000_000,
    "Cat1":                500_000,
    "Cat3":                100_000_000,
    "Cat4":                100_000_000,
    "Cat5":                1_000_000,
    "Cat6":                10_000_000,
    "Cat7":                10_000_000,
    "Cat9":                100_000_000,
    "Cat12":               1_000_000,
}

_AC_S2MB_STRUMENTI: list[str] = ["GO", "PPA", "RESIDUAL"]

_AC_CAT1_METHODS: list[str] = ["mass-based", "spend-based"]
_AC_CAT3_METHODS: list[str] = ["activity-based", "fuel-based"]
_AC_CAT46_METHODS: list[str] = ["distance-based", "mass-based", "activity-based"]
_AC_CAT5_METHODS: list[str] = ["mass-based", "activity-based"]
_AC_CAT67_METHODS: list[str] = ["distance-based", "spend-based", "activity-based"]
_AC_CAT12_METHODS: list[str] = ["mass-based", "activity-based"]

_AC_METHODS_BY_SUBSCOPE: dict[str, list[str]] = {
    "Cat1":  _AC_CAT1_METHODS,
    "Cat3":  _AC_CAT3_METHODS,
    "Cat4":  _AC_CAT46_METHODS,
    "Cat5":  _AC_CAT5_METHODS,
    "Cat6":  _AC_CAT67_METHODS,
    "Cat7":  _AC_CAT67_METHODS,
    "Cat9":  _AC_CAT46_METHODS,
    "Cat12": _AC_CAT12_METHODS,
}

_AC_GWP_OPTIONS: list[str] = ["AR6", "AR5"]

# Session-state key for the last 5 successful inserts (quick-repeat memo)
_AC_HISTORY_KEY = "ac_recent_inserts"
# Max recent entries shown
_AC_HISTORY_MAX = 5

# ---------------------------------------------------------------------------
# Helper: build canonical API payload from the collected form values
# ---------------------------------------------------------------------------


def _ac_build_payload(
    sub_scope_key: str,
    codice_sito: str | None,
    anno: int,
    quantita_str: str,
    unita: str,
    gwp_set: str,
    note: str,
    *,
    strumento_mb: str | None = None,
    sottocategoria: str | None = None,
    metodo: str | None = None,
    regulatory_stream: str = "CSRD_ESRS_E1",
) -> dict:
    """Map UI form state to the CalcInputRequest body (§10)."""
    # Derive API scope, sub_scope and optional combustibile / categoria_s3
    if sub_scope_key.startswith("combustion_"):
        combustibile_map = {
            "combustion_GAS_NAT": "GAS_NAT",
            "combustion_GASOLIO": "GASOLIO",
            "combustion_BENZINA": "BENZINA",
        }
        return {
            "scope": 1,
            "sub_scope": "combustion",
            "combustibile": combustibile_map[sub_scope_key],
            "codice_sito": codice_sito,
            "anno": anno,
            "quantita": quantita_str,
            "unita": unita,
            "gwp_set": gwp_set,
            "regulatory_stream": regulatory_stream,
            "disclosure_notes": note or None,
        }
    if sub_scope_key in ("process_direct", "process_caco3"):
        payload: dict = {
            "scope": 1,
            "sub_scope": "process",
            "codice_sito": "IANO",   # only site with decarb process
            "anno": anno,
            "quantita": quantita_str,
            "unita": unita,
            "gwp_set": gwp_set,
            "regulatory_stream": regulatory_stream,
            "disclosure_notes": note or None,
        }
        if sub_scope_key == "process_direct":
            payload["process_mode"] = "direct_tco2"
        else:
            payload["process_mode"] = "caco3_mass"
        return payload
    if sub_scope_key == "LB":
        return {
            "scope": 2,
            "sub_scope": "LB",
            "codice_sito": codice_sito,
            "anno": anno,
            "quantita": quantita_str,
            "unita": unita,
            "gwp_set": gwp_set,
            "regulatory_stream": regulatory_stream,
            "disclosure_notes": note or None,
        }
    if sub_scope_key == "MB":
        return {
            "scope": 2,
            "sub_scope": "MB",
            "codice_sito": codice_sito,
            "anno": anno,
            "strumento_mb": strumento_mb,
            "quantita": quantita_str,
            "unita": unita,
            "gwp_set": gwp_set,
            "regulatory_stream": regulatory_stream,
            "disclosure_notes": note or None,
        }
    # Scope 3 categories
    cat_num = int(sub_scope_key.replace("Cat", ""))
    return {
        "scope": 3,
        "sub_scope": sub_scope_key,
        "categoria_s3": cat_num,
        "sottocategoria": sottocategoria or None,
        "metodo": metodo,
        "codice_sito": codice_sito or None,   # optional for Scope 3
        "anno": anno,
        "quantita": quantita_str,
        "unita": unita,
        "gwp_set": gwp_set,
        "regulatory_stream": regulatory_stream,
        "disclosure_notes": note or None,
    }


# ---------------------------------------------------------------------------
# Helper: render the preview result card
# ---------------------------------------------------------------------------


def _ac_render_preview(preview: dict, lang: str) -> None:
    """Render the tCO2e preview result with breakdown, formula, and metadata."""
    tco2e_str = preview.get("tco2e", "—")
    gwp_set_used = preview.get("gwp_set", "AR6")
    methodology = preview.get("methodology", "")
    fm = preview.get("factor_metadata") or {}
    breakdown = preview.get("breakdown") or {}
    dq = preview.get("dq_findings") or []
    disclosure = preview.get("disclosure_notes", "")

    # --- Hero metric ---
    # ``tco2e_str`` is coerced to float before formatting so an attacker-controlled
    # backend cannot smuggle markup through it; ``gwp_set_used`` originates from
    # the API response (sourced from the factor catalog DB) and is escaped to
    # eliminate any XSS surface even though the value is policy-constrained.
    import html as _html  # noqa: PLC0415

    st.markdown(
        f"""
<div class="ct-preview-card">
  <div style="font-size:0.72rem;font-weight:600;letter-spacing:0.08em;
              text-transform:uppercase;color:#9a9a9a;margin-bottom:0.4rem;">
    Risultato anteprima
  </div>
  <span class="ct-preview-tco2e">{float(tco2e_str):,.6f}</span>
  <span class="ct-preview-unit">tCO2e</span>
  <span class="ct-gwp-chip">{_html.escape(str(gwp_set_used))}</span>
</div>
""",
        unsafe_allow_html=True,
    )

    # st.metric for screen-readers and alternative text
    st.metric(
        label=_("auto_calc_factor_used_label", lang) + " — tCO2e totale",
        value=f"{float(tco2e_str):,.6f}",
        help=(
            "Valore calcolato dal backend. Non modificabile qui: deriva "
            "dal fattore di emissione risolto e dalla quantita inserita."
        ),
    )

    # --- Factor card ---
    if fm:
        vintage_offset = fm.get("vintage_offset_applied", False)
        with st.expander(_("auto_calc_factor_used_label", lang), expanded=True):
            fc1, fc2 = st.columns(2)
            with fc1:
                st.caption("Factor ID")
                st.code(fm.get("primary_factor_id", "—"), language="text")
                st.caption(f"Fonte: **{fm.get('factor_source', '—')}**")
                st.caption(f"Versione: {fm.get('factor_version', '—')}")
            with fc2:
                st.caption(f"Vintage: {fm.get('vintage', '—')}")
                st.caption(f"Unita fattore: `{fm.get('unit', '—')}`")
                st.caption(f"Metodologia: {methodology}")
            if vintage_offset:
                # safe: static markup, no user/db data
                st.markdown(
                    '<div class="ct-vintage-warn">'
                    '⚠ Vintage offset applicato — fattore piu recente disponibile '
                    'usato in base alla regola closest-prior (GHG Protocol §6.3).'
                    "</div>",
                    unsafe_allow_html=True,
                )

    # --- Gas breakdown table ---
    # ``gas_components`` rows come from the backend (factor_catalog DB).  Each
    # cell value is HTML-escaped before interpolation to neutralise any XSS
    # vector via crafted factor metadata (CWE-79).
    gas_components = breakdown.get("gas_components") or []
    if gas_components:
        with st.expander("Scomposizione per gas", expanded=False):
            rows_html = "".join(
                f"<tr>"
                f"<td>{_html.escape(str(gc.get('gas','')))}</td>"
                f"<td class='ct-num'>{_html.escape(str(gc.get('factor_value','—')))}</td>"
                f"<td class='ct-num'>{_html.escape(str(gc.get('gwp','1')))}</td>"
                f"<td class='ct-num'>{float(gc.get('contribution_tco2e','0')):,.6f}</td>"
                f"</tr>"
                for gc in gas_components
            )
            st.markdown(
                f"""
<table class="ct-breakdown-table">
  <thead><tr>
    <th>Gas</th><th>Fattore</th><th>GWP</th><th>Contributo (tCO2e)</th>
  </tr></thead>
  <tbody>{rows_html}</tbody>
</table>
""",
                unsafe_allow_html=True,
            )

    # --- Human-readable formula ---
    # Build it from available data when the backend doesn't return one.
    # The formula embeds backend-sourced values (``primary_factor_val``,
    # ``unit``, ``tco2e_str``) so the rendered HTML must be escaped (CWE-79).
    primary_factor_val = fm.get("primary_factor_val") or (
        gas_components[0].get("factor_value") if gas_components else None
    )
    if primary_factor_val:
        formula_str = (
            f"{tco2e_str} tCO2e  =  quantita × {primary_factor_val} "
            f"[{fm.get('unit','')}] × GWP × 0.001"
        )
    else:
        formula_str = f"tCO2e = {tco2e_str}"

    st.markdown(f"**{_('auto_calc_formula_label', lang)}**")
    st.markdown(
        f'<div class="ct-formula-block">{_html.escape(formula_str)}</div>',
        unsafe_allow_html=True,
    )

    # --- Biogenic memo ---
    bio = breakdown.get("co2_biogenic_tonne")
    if bio and float(bio) != 0.0:
        st.info(
            f"Memo biogenico (E1-7, non incluso nel totale): {float(bio):,.6f} t CO2 biogenico",
            icon="🌿",
        )

    # --- DQ findings ---
    if dq:
        failing = [f for f in dq if f.get("severity") not in ("PASS", "INFO")]
        if failing:
            with st.expander("Avvisi DQ", expanded=True):
                for f in failing:
                    sev = f.get("severity", "WARN")
                    icon = "🔴" if sev == "FAIL" else "🟡"
                    st.warning(f"{icon} **{f.get('rule','')}** — {f.get('message', sev)}")
        else:
            st.success("Tutti i controlli DQ superati.", icon="✅")

    # --- Disclosure notes footer ---
    if disclosure:
        st.caption(f"Note disclosure: {disclosure}")


# ---------------------------------------------------------------------------
# Auto-calc tab body
# ---------------------------------------------------------------------------

with tab_autocalc:
    st.subheader(_("auto_calc_tab_title", lang))
    st.caption(
        "Inserisci un consumo, vedi il calcolo tCO2e in tempo reale, "
        "conferma per registrare nel ledger. "
        "Richiede ruolo **editor** o **admin**."
    )

    # Role gate
    if role not in ("editor", "admin"):
        st.warning(
            "Il tuo ruolo (`viewer`) non puo registrare emissioni tramite il calcolo automatico. "
            "Richiedi accesso editor o admin.",
            icon="🔒",
        )

    # -----------------------------------------------------------------------
    # Section 1 — Scope + sito + sub-scope
    #
    # Decision #7 (auto_calc_design.md §12): "Processo (decarbonatazione)"
    # is visible ONLY when the selected site is STABILIMENTO_PRODUTTIVO.
    # The site selector is therefore rendered BEFORE the sub-scope selector
    # for Scope 1 so the sub-scope list can be filtered accordingly.
    # -----------------------------------------------------------------------
    # safe: static markup, no user/db data
    st.markdown('<div class="ct-autocalc-form">', unsafe_allow_html=True)

    # Load site catalogue from API (cached, TTL 5 min).
    _ac_all_sites: list[Site] = get_sites()
    _ac_site_codes: list[str] = [s.codice_sito for s in _ac_all_sites]

    ac_col1, ac_col2 = st.columns([1, 2])
    with ac_col1:
        ac_scope = st.selectbox(
            _("auto_calc_scope", lang),
            options=_AC_SCOPE_OPTIONS,
            format_func=lambda s: f"Scope {s}",
            key="ac_scope",
            help=(
                "Scope 1: emissioni dirette. "
                "Scope 2: elettricita acquistata. "
                "Scope 3: catena del valore."
            ),
        )

    # Task 1: when the user switches to Scope 3, reset the site state to None
    # so that any previously-selected site does not leak into the S3 payload.
    _prev_scope_key = "ac_scope_prev"
    _prev_scope = st.session_state.get(_prev_scope_key)
    if _prev_scope is not None and _prev_scope != ac_scope and ac_scope == 3:
        st.session_state.pop("ac_site", None)
        st.session_state.pop("ac_site_s3", None)
    st.session_state[_prev_scope_key] = ac_scope

    # For Scope 1 we need the site BEFORE building the sub-scope list
    # (decision #7): show the site picker in col2 first, then sub-scope below.
    # For Scope 2/3 we keep the original ordering (scope → sub-scope → site).
    _ac_early_site_selection: str | None = None
    if ac_scope == 1:
        with ac_col2:
            _s1_site_opts = _ac_site_codes
            _s1_site_labels = {
                s.codice_sito: s.dropdown_label for s in _ac_all_sites
            }
            _s1_site_key = st.selectbox(
                "Codice sito",
                options=_s1_site_opts,
                format_func=lambda c: _s1_site_labels.get(c, c),
                key="ac_site",
                help=(
                    "Sito operativo a cui attribuire l'emissione. "
                    "La voce 'Processo (decarbonatazione)' appare solo per stabilimenti produttivi."
                ),
            )
            _ac_early_site_selection = _s1_site_key

    # Build the sub-scope list, filtering out process keys when the site is
    # not a STABILIMENTO_PRODUTTIVO (decision #7).
    _ac_selected_site_obj: Site | None = (
        get_site(_ac_early_site_selection) if _ac_early_site_selection else None
    )
    _is_stabilimento = (
        _ac_selected_site_obj is not None
        and _ac_selected_site_obj.site_type == "STABILIMENTO_PRODUTTIVO"
    )

    def _ac_filter_subscopes(scope: int, site_obj: Site | None) -> list[str]:
        """Return allowed sub-scope keys, honouring decision #7 for Scope 1."""
        keys = _AC_SUBSCOPE_BY_SCOPE[scope]
        if scope != 1:
            return keys
        # For Scope 1: hide process_ keys unless the site is a stabilimento.
        is_stab = site_obj is not None and site_obj.site_type == "STABILIMENTO_PRODUTTIVO"
        if is_stab:
            return keys
        return [k for k in keys if not k.startswith("process_")]

    ac_subscope_keys = _ac_filter_subscopes(ac_scope, _ac_selected_site_obj)

    _ac_subscope_col = ac_col1 if ac_scope == 1 else ac_col2
    with _ac_subscope_col if ac_scope != 1 else st.container():
        # For Scope 1 place sub-scope below scope selector (full width).
        # For Scope 2/3 use the right column as before.
        if ac_scope == 1:
            _ss_col, _ = st.columns([2, 1])
            _ss_ctx = _ss_col
        else:
            _ss_ctx = ac_col2

    with _ss_ctx:
        ac_subscope_key = st.selectbox(
            _("auto_calc_subscope", lang),
            options=ac_subscope_keys,
            format_func=lambda k: _AC_SUBSCOPE_LABELS[k],
            key="ac_subscope",
            help="Seleziona la categoria specifica corrispondente alla fonte di emissione.",
        )

    # Caption explaining why process options are hidden (decision #7, colorblind-safe).
    if ac_scope == 1 and _ac_selected_site_obj is not None and not _is_stabilimento:
        st.caption(
            f"ℹ️ La voce 'Processo (decarbonatazione)' è disponibile solo per stabilimenti "
            f"produttivi. Il sito {_ac_selected_site_obj.codice_sito} è di tipo "
            f"{_ac_selected_site_obj.site_type_label}."
        )

    st.divider()

    # -----------------------------------------------------------------------
    # Section 2 — Conditional fields by sub-scope
    # -----------------------------------------------------------------------

    is_s1_combustion = ac_subscope_key.startswith("combustion_")
    is_s1_process    = ac_subscope_key.startswith("process_")
    is_s2_lb         = ac_subscope_key == "LB"
    is_s2_mb         = ac_subscope_key == "MB"
    is_s3            = ac_scope == 3

    ac_codice_sito: str | None = None
    ac_strumento_mb: str | None = None
    ac_sottocategoria: str | None = None
    ac_metodo: str | None = None

    # Site label helpers for dropdown
    _all_site_labels = {s.codice_sito: s.dropdown_label for s in _ac_all_sites}

    f_col1, f_col2 = st.columns(2)

    with f_col1:
        # --- Site selector ---
        if ac_scope == 1:
            # Scope 1: site was already shown above the sub-scope picker
            # (decision #7 ordering). Reuse the value from session_state.
            ac_codice_sito = _ac_early_site_selection or (
                _ac_site_codes[0] if _ac_site_codes else None
            )
            # For process sub-scopes the backend enforces IANO; show a
            # locked text input as a hint (not used for routing — the
            # actual codice_sito comes from _ac_early_site_selection which
            # for process paths the form already constrains to IANO only
            # via the "Stabilimento produttivo" site-type filter above).
            if is_s1_process and ac_codice_sito:
                st.text_input(
                    "Codice sito (confermato)",
                    value=ac_codice_sito,
                    disabled=True,
                    help=(
                        "Il processo di decarbonatazione CaCO3 è attivo solo per "
                        "stabilimenti produttivi. Sito selezionato sopra."
                    ),
                )
        elif is_s3:
            # Task 1: Scope 3 è corporate — nessun codice sito.
            # Il dropdown "Codice sito" è nascosto e codice_sito è sempre None.
            st.caption(
                "ℹ️ Scope 3 è corporate: il calcolo aggrega per tutto il gruppo, "
                "non per singola sede."
            )
            ac_codice_sito = None
        else:
            # Scope 2: live site list from API
            ac_codice_sito = st.selectbox(
                "Codice sito",
                options=_ac_site_codes,
                format_func=lambda c: _all_site_labels.get(c, c),
                key="ac_site",
                help="Sito operativo a cui attribuire l'emissione (perimetro consolidamento).",
            )

        # --- Year ---
        ac_anno = st.number_input(
            "Anno fiscale",
            min_value=2020,
            max_value=dt.date.today().year + 1,
            value=dt.date.today().year - 1,
            step=1,
            key="ac_anno",
            help=(
                "Anno di competenza del consumo. "
                "Il resolver applica la regola closest-prior vintage (§3 design doc)."
            ),
        )

    with f_col2:
        # --- Quantity + unit ---
        available_units = _AC_UNITS.get(ac_subscope_key, ["kWh"])
        unit_is_readonly = ac_subscope_key == "process_direct"

        ac_quantita = st.number_input(
            _("auto_calc_quantita", lang),
            min_value=0.0,
            value=0.0,
            step=0.001,
            format="%.6f",
            key="ac_quantita",
            help=(
                "Valore del consumo nell'unita selezionata. "
                "Inviato come stringa al backend per preservare la precisione Decimal (§9)."
            ),
        )

        if unit_is_readonly:
            st.text_input(
                _("auto_calc_unita", lang),
                value="tCO2",
                disabled=True,
                help="Unita fissa per inserimento diretto tCO2 (modalita A processo).",
            )
            ac_unita = "tCO2"
        else:
            ac_unita = st.selectbox(
                _("auto_calc_unita", lang),
                options=available_units,
                key="ac_unita",
                help=(
                    "Seleziona l'unita che corrisponde a come hai misurato il consumo. "
                    "Il backend risolve il fattore nella stessa unita (no conversioni implicite NCV)."
                ),
            )

    # --- GWP set (Advanced) ---
    with st.expander("Impostazioni avanzate (GWP set, note)", expanded=False):
        adv_col1, adv_col2 = st.columns(2)
        with adv_col1:
            ac_gwp_set = st.selectbox(
                "Set GWP",
                options=_AC_GWP_OPTIONS,
                index=0,
                key="ac_gwp",
                help=(
                    "AR6 (default CSRD ESRS E1). "
                    "AR5 per report EU ETS Phase IV (regulatory_stream = EU_ETS_PHASE_IV)."
                ),
            )
            if ac_gwp_set == "AR5":
                ac_regulatory_stream = "EU_ETS_PHASE_IV"
            else:
                ac_regulatory_stream = "CSRD_ESRS_E1"
        with adv_col2:
            ac_note = st.text_area(
                "Note (opzionali)",
                max_chars=500,
                key="ac_note",
                placeholder="Es. Lettura contatore gas naturale Q1 2025, fattura n. 12345.",
                help="Aggiunge un suffisso alle disclosure_notes della riga registrata.",
            )

    # --- Scope 2 MB: strumento ---
    if is_s2_mb:
        ac_strumento_mb = st.selectbox(
            "Strumento MB",
            options=_AC_S2MB_STRUMENTI,
            key="ac_strumento_mb",
            help=(
                "GO (Garanzia d'Origine): richiede evidenza QC1-QC8 nel catalogo. "
                "PPA: contratto di acquisto diretto. "
                "RESIDUAL: fattore residuale AIB (default)."
            ),
        )

    # --- Scope 3: sottocategoria + metodo ---
    if is_s3:
        sc3_col1, sc3_col2 = st.columns(2)
        with sc3_col1:
            ac_sottocategoria = st.text_input(
                "Sottocategoria / materiale",
                key="ac_sottocategoria",
                placeholder=(
                    "Es. Argille, ECOINV_CARDBOARD_V3_10, WTT_GAS_NAT"
                    if ac_subscope_key in ("Cat1", "Cat3") else
                    "Es. aereo short-haul, TIR, imballaggi primari"
                ),
                help=(
                    "Codice del materiale / rotta / prodotto che il backend mappa al fattore. "
                    "Per Cat 1: usa codici ECOINV_* (mass-based) o EXIO_* (spend-based). "
                    "Lascia vuoto per usare il fattore default della categoria."
                ),
            )
        with sc3_col2:
            methods = _AC_METHODS_BY_SUBSCOPE.get(ac_subscope_key, ["activity-based"])
            ac_metodo = st.selectbox(
                "Metodo di calcolo",
                options=methods,
                key="ac_metodo",
                help=(
                    "Approccio metodologico che il backend usa per selezionare il fattore. "
                    "Mass-based: quantita in t. Spend-based: quantita in EUR. "
                    "Distance-based: quantita in km o t·km."
                ),
            )

    st.divider()

    # -----------------------------------------------------------------------
    # Section 3 — Preview
    # -----------------------------------------------------------------------

    # Track preview state
    if "ac_preview_result" not in st.session_state:
        st.session_state["ac_preview_result"] = None
    if "ac_preview_payload" not in st.session_state:
        st.session_state["ac_preview_payload"] = None
    if "ac_preview_error" not in st.session_state:
        st.session_state["ac_preview_error"] = None

    btn_col1, btn_col2, btn_col3 = st.columns([2, 2, 1])

    with btn_col1:
        preview_clicked = st.button(
            _("auto_calc_preview_btn", lang),
            key="ac_btn_preview",
            help="Invia i dati al backend per il calcolo in anteprima (nessuna scrittura nel registro).",
            disabled=(role not in ("editor", "admin")),
        )

    with btn_col3:
        clear_clicked = st.button(
            _("auto_calc_clear_btn", lang),
            key="ac_btn_clear",
            help="Azzera tutti i campi e il risultato dell'anteprima.",
        )

    if clear_clicked:
        # Clear form-related state keys (ac_site_s3 removed: S3 no longer has a site picker)
        for key in (
            "ac_scope", "ac_subscope", "ac_site", "ac_anno",
            "ac_quantita", "ac_unita", "ac_gwp", "ac_note",
            "ac_strumento_mb", "ac_sottocategoria", "ac_metodo",
            "ac_preview_result", "ac_preview_payload", "ac_preview_error",
            "_inflight_ac_insert", "ac_scope_prev",
        ):
            st.session_state.pop(key, None)
        st.rerun()

    if preview_clicked:
        quantita_str = f"{ac_quantita:.6f}".rstrip("0").rstrip(".")
        if not quantita_str or float(quantita_str) < 0:
            st.error("La quantita deve essere un numero positivo.")
        else:
            payload = _ac_build_payload(
                sub_scope_key=ac_subscope_key,
                codice_sito=ac_codice_sito,
                anno=int(ac_anno),
                quantita_str=quantita_str,
                unita=ac_unita,
                gwp_set=ac_gwp_set,
                note=ac_note if "ac_note" in st.session_state else "",
                strumento_mb=ac_strumento_mb,
                sottocategoria=ac_sottocategoria,
                metodo=ac_metodo,
                regulatory_stream=ac_regulatory_stream,
            )
            token = st.session_state.get("token", "")
            with st.spinner("Calcolo in corso..."):
                try:
                    result = calc_preview(payload, token=token)
                    st.session_state["ac_preview_result"] = result
                    st.session_state["ac_preview_payload"] = payload
                    st.session_state["ac_preview_error"] = None
                except AutoCalcError as exc:
                    st.session_state["ac_preview_result"] = None
                    st.session_state["ac_preview_error"] = str(exc.detail)

    # Render preview result or empty state
    preview_result = st.session_state.get("ac_preview_result")
    preview_error  = st.session_state.get("ac_preview_error")

    if preview_error:
        detail_msg = preview_error
        # 422 site_type_invalid: show a specific, actionable alert
        # (task #4 — graceful fallback for stale-cache bypass).
        # Detection: the backend embeds "site_type_invalid" in the detail.
        if "site_type_invalid" in detail_msg.lower() or "site_type_invalid" in detail_msg:
            # Try to extract structured fields from the detail string.
            _err_sito = ac_codice_sito or "?"
            _err_site_obj = get_site(_err_sito)
            _err_type_label = (
                _err_site_obj.site_type_label if _err_site_obj else _err_sito
            )
            st.error(
                f"⚠️ **Tipo sito non valido per questa operazione.**\n\n"
                f"Il sito **{_err_sito}** è di tipo **{_err_type_label}**: "
                f"le emissioni di processo (decarbonatazione CaCO3) sono ammesse "
                f"solo per siti di tipo Stabilimento produttivo.\n\n"
                f"Dettaglio backend: {detail_msg}",
            )
        # Surface 422 missing-factor detail directly (design doc §6 requirement)
        elif "fattore" in detail_msg.lower() or "factor" in detail_msg.lower() or "missing" in detail_msg.lower():
            st.error(
                f"{_('auto_calc_no_factor', lang)}\n\nDettaglio: {detail_msg}",
                icon="🔍",
            )
        else:
            st.error(detail_msg)
    elif preview_result is not None:
        _ac_render_preview(preview_result, lang)
    else:
        # Empty state card — safe: static markup, no user/db data
        st.markdown(
            """
<div class="ct-preview-empty">
  <div class="ct-pe-icon">🧮</div>
  <div class="ct-pe-text">
    Compila i campi sopra e clicca <strong>Calcola anteprima</strong>
    per vedere il risultato in tCO2e.
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

    # -----------------------------------------------------------------------
    # Section 4 — Confirm and insert
    # -----------------------------------------------------------------------
    preview_done = preview_result is not None

    with btn_col2:
        insert_disabled = (
            not preview_done
            or role not in ("editor", "admin")
            or st.session_state.get("_inflight_ac_insert", False)
        )
        insert_clicked = st.button(
            _("auto_calc_insert_btn", lang),
            key="ac_btn_insert",
            type="primary",
            disabled=insert_disabled,
            help=(
                "Registra la riga nel ledger. Disponibile solo dopo una anteprima valida. "
                "Il registro e append-only: l'operazione non e reversibile."
            ),
        )

    if insert_clicked and preview_done and _submit_once("ac_insert"):
        stored_payload = st.session_state.get("ac_preview_payload", {})

        # Anomaly check: if quantita > the category's typical ceiling → warn
        try:
            q_float = float(stored_payload.get("quantita", "0"))
        except (ValueError, TypeError):
            q_float = 0.0
        ceil_val = _AC_ANOMALY_CEIL.get(ac_subscope_key, float("inf"))

        # Store anomaly state so the confirmation expander is shown below
        if q_float > ceil_val:
            st.session_state["ac_anomaly_pending"] = True
            st.session_state["ac_anomaly_payload"] = stored_payload
            st.session_state["_inflight_ac_insert"] = False  # allow re-click
        else:
            st.session_state.pop("ac_anomaly_pending", None)
            token_ins = st.session_state.get("token", "")
            with st.spinner("Registrazione in corso..."):
                try:
                    result_ins = calc_insert(stored_payload, token=token_ins)
                    emission_id = result_ins.get("emission_id", "—")
                    st.success(
                        f"{_('auto_calc_inserted_ok', lang)} `{emission_id}`",
                        icon="✅",
                    )
                    if hasattr(st, "toast"):
                        st.toast("Riga inserita nel registro", icon="✅")

                    # Add to history
                    history = st.session_state.get(_AC_HISTORY_KEY, [])
                    tco2e_val = result_ins.get("tco2e", "—")
                    label = (
                        f"{_AC_SUBSCOPE_LABELS.get(ac_subscope_key, ac_subscope_key)} "
                        f"· {ac_anno} · {q_float:,.3f} {ac_unita}"
                    )
                    history.insert(0, {
                        "emission_id": emission_id,
                        "tco2e": tco2e_val,
                        "label": label,
                        "payload": stored_payload,
                    })
                    st.session_state[_AC_HISTORY_KEY] = history[:_AC_HISTORY_MAX]

                    # Invalidate read-side caches so the new row appears in Audit Trail.
                    for fn in (fetch_emissions, fetch_factor_catalog):
                        clear = getattr(fn, "clear", None)
                        if callable(clear):
                            try:
                                clear()
                            except (AttributeError, TypeError):
                                pass

                    # Audit trail CTA
                    if hasattr(st, "page_link"):
                        st.page_link(
                            "pages/7_Audit_Trail.py",
                            label=_("view_in_audit_trail", lang),
                            icon="🔍",
                        )

                    # Task 2: "Replica come Cat3 WTT" — shown only after a
                    # successful Scope 1 Combustion insert (decisione #5).
                    if is_s1_combustion:
                        _combustibile_map_inv = {
                            "combustion_GAS_NAT": "GAS_NAT",
                            "combustion_GASOLIO": "GASOLIO",
                            "combustion_BENZINA": "BENZINA",
                        }
                        _s1_combustibile = _combustibile_map_inv.get(
                            ac_subscope_key, ""
                        )
                        # Persist the WTT pre-fill data in session_state so the
                        # button click on rerun can populate the form.
                        st.session_state["ac_wtt_prefill"] = {
                            "quantita": q_float,
                            "unita": ac_unita,
                            "combustibile": _s1_combustibile,
                            "anno": int(ac_anno),
                        }

                    # Reset form state for next entry
                    for key in (
                        "ac_preview_result", "ac_preview_payload",
                        "ac_preview_error", "_inflight_ac_insert",
                    ):
                        st.session_state.pop(key, None)

                except AutoCalcError as exc:
                    st.error(str(exc.detail), icon="🚫")
                    st.session_state["_inflight_ac_insert"] = False

    # Anomaly confirmation: shown inline when quantity exceeds ceiling
    if st.session_state.get("ac_anomaly_pending"):
        anomaly_payload = st.session_state.get("ac_anomaly_payload", {})
        try:
            anomaly_q = float(anomaly_payload.get("quantita", "0"))
        except (ValueError, TypeError):
            anomaly_q = 0.0
        with st.expander("Conferma quantita anomala", expanded=True):
            st.warning(
                f"La quantita inserita ({anomaly_q:,.2f}) "
                f"supera la soglia tipica per questa categoria "
                f"({_AC_ANOMALY_CEIL.get(ac_subscope_key, 0):,.0f}). "
                "Verifica che il valore sia corretto prima di registrare.",
                icon="⚠️",
            )
            anom_col1, anom_col2 = st.columns([1, 1])
            with anom_col1:
                if st.button(
                    "Confermo — registra comunque",
                    type="primary",
                    key="ac_anomaly_confirm",
                ):
                    token_anom = st.session_state.get("token", "")
                    with st.spinner("Registrazione in corso..."):
                        try:
                            result_anom = calc_insert(anomaly_payload, token=token_anom)
                            emission_id_anom = result_anom.get("emission_id", "—")
                            st.success(
                                f"{_('auto_calc_inserted_ok', lang)} `{emission_id_anom}`",
                                icon="✅",
                            )
                            if hasattr(st, "toast"):
                                st.toast("Riga inserita nel registro", icon="✅")
                            history = st.session_state.get(_AC_HISTORY_KEY, [])
                            history.insert(0, {
                                "emission_id": emission_id_anom,
                                "tco2e": result_anom.get("tco2e", "—"),
                                "label": f"{ac_subscope_key} · {ac_anno}",
                                "payload": anomaly_payload,
                            })
                            st.session_state[_AC_HISTORY_KEY] = history[:_AC_HISTORY_MAX]
                            for key in (
                                "ac_anomaly_pending", "ac_anomaly_payload",
                                "ac_preview_result", "ac_preview_payload",
                                "ac_preview_error",
                            ):
                                st.session_state.pop(key, None)
                        except AutoCalcError as exc:
                            st.error(str(exc.detail), icon="🚫")
            with anom_col2:
                if st.button("Annulla — torna al form", key="ac_anomaly_cancel"):
                    st.session_state.pop("ac_anomaly_pending", None)
                    st.session_state.pop("ac_anomaly_payload", None)
                    st.rerun()

    # -----------------------------------------------------------------------
    # Task 2 — "Replica come Cat3 WTT" button + pre-filled WTT form
    #
    # Shown after a successful Scope 1 Combustion insert.  The session_state
    # key ``ac_wtt_prefill`` is set in the insert success branch above and
    # cleared when the user submits or dismisses the WTT form.
    # -----------------------------------------------------------------------
    _wtt_prefill = st.session_state.get("ac_wtt_prefill")
    if _wtt_prefill is not None and role in ("editor", "admin"):
        st.divider()
        if st.button(
            "Replica come Cat3 WTT (Well-To-Tank)",
            key="ac_btn_wtt_replicate",
            help=(
                "Crea automaticamente la corrispondente riga Cat3 'Well-To-Tank' "
                "per le emissioni upstream del combustibile (estrazione, raffinazione, "
                "trasporto). Da fare per coerenza con GHG Protocol Scope 3 Standard Cat. 3."
            ),
        ):
            st.session_state["ac_wtt_form_open"] = True

    if st.session_state.get("ac_wtt_form_open") and _wtt_prefill is not None:
        with st.container(border=True):
            st.markdown("**Pre-compilazione Cat3 WTT (Well-To-Tank)**")
            st.caption(
                "Verifica i valori pre-compilati dalla riga Scope 1 e conferma "
                "per registrare la corrispondente riga Cat3 upstream."
            )
            _wtt_q = st.number_input(
                "Quantità",
                value=float(_wtt_prefill.get("quantita", 0.0)),
                min_value=0.0,
                step=0.001,
                format="%.6f",
                key="ac_wtt_quantita",
                help="Pre-compilato dalla riga Scope 1 appena inserita.",
            )
            _wtt_unit_opts = _AC_UNITS.get("Cat3", ["Sm3", "kWh", "MWh", "t"])
            _wtt_unit_default = _wtt_prefill.get("unita", _wtt_unit_opts[0])
            _wtt_unit_idx = (
                _wtt_unit_opts.index(_wtt_unit_default)
                if _wtt_unit_default in _wtt_unit_opts
                else 0
            )
            _wtt_unita = st.selectbox(
                "Unità",
                options=_wtt_unit_opts,
                index=_wtt_unit_idx,
                key="ac_wtt_unita",
                help="Stessa unità della riga Scope 1.",
            )
            _wtt_sottocategoria = st.text_input(
                "Sottocategoria / combustibile",
                value=_wtt_prefill.get("combustibile", ""),
                key="ac_wtt_sottocategoria",
                help=(
                    "Pre-compilato dal combustibile Scope 1. "
                    "Lascia invariato per il fattore WTT default."
                ),
            )
            _wtt_anno = st.number_input(
                "Anno fiscale",
                value=int(_wtt_prefill.get("anno", dt.date.today().year - 1)),
                min_value=2020,
                max_value=dt.date.today().year + 1,
                step=1,
                key="ac_wtt_anno",
            )
            _wtt_col1, _wtt_col2 = st.columns([1, 1])
            with _wtt_col1:
                if st.button(
                    "Conferma e registra Cat3 WTT",
                    type="primary",
                    key="ac_wtt_confirm",
                    disabled=st.session_state.get("_inflight_ac_wtt", False),
                ):
                    if _wtt_q <= 0:
                        st.error("La quantità deve essere maggiore di zero.")
                    elif not _wtt_sottocategoria.strip():
                        st.error("Inserisci la sottocategoria / combustibile.")
                    elif not st.session_state.get("_inflight_ac_wtt"):
                        st.session_state["_inflight_ac_wtt"] = True
                        _wtt_payload = {
                            "scope": 3,
                            "sub_scope": "Cat3",
                            "categoria_s3": 3,
                            "sottocategoria": _wtt_sottocategoria.strip() or "WTT_FUEL",
                            "metodo": "fuel-based",
                            "codice_sito": None,
                            "anno": int(_wtt_anno),
                            "quantita": f"{_wtt_q:.6f}".rstrip("0").rstrip("."),
                            "unita": _wtt_unita,
                            "gwp_set": "AR6",
                            "regulatory_stream": "CSRD_ESRS_E1",
                            "disclosure_notes": "Cat3 WTT replica da S1 combustione",
                        }
                        _tok_wtt = st.session_state.get("token", "")
                        with st.spinner("Registrazione Cat3 WTT in corso..."):
                            try:
                                _res_wtt = calc_insert(_wtt_payload, token=_tok_wtt)
                                _eid_wtt = _res_wtt.get("emission_id", "—")
                                st.success(
                                    f"Cat3 WTT inserita. Emission ID: `{_eid_wtt}`",
                                    icon="✅",
                                )
                                for fn in (fetch_emissions, fetch_factor_catalog):
                                    _clr = getattr(fn, "clear", None)
                                    if callable(_clr):
                                        try:
                                            _clr()
                                        except (AttributeError, TypeError):
                                            pass
                                for key in (
                                    "ac_wtt_prefill", "ac_wtt_form_open",
                                    "_inflight_ac_wtt",
                                ):
                                    st.session_state.pop(key, None)
                            except AutoCalcError as exc:
                                st.error(str(exc.detail), icon="🚫")
                                st.session_state["_inflight_ac_wtt"] = False
            with _wtt_col2:
                if st.button("Annulla WTT", key="ac_wtt_cancel"):
                    for key in (
                        "ac_wtt_prefill", "ac_wtt_form_open", "_inflight_ac_wtt",
                    ):
                        st.session_state.pop(key, None)
                    st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    # -----------------------------------------------------------------------
    # Recent insertions memo (last 5 quick-repeat)
    # -----------------------------------------------------------------------
    history = st.session_state.get(_AC_HISTORY_KEY, [])
    if history:
        st.divider()
        st.markdown("**Ultimi inserimenti (sessione corrente)**")
        st.caption(
            "Clicca su un inserimento per visualizzarlo in Audit Trail. "
            "I dati qui non ripopolano il form (ogni inserimento e intenzionale)."
        )
        for entry in history:
            h_col1, h_col2 = st.columns([4, 1])
            with h_col1:
                st.markdown(
                    f'<div class="ct-recent-entry">'
                    f'<span class="ct-re-tco2e">{entry.get("tco2e","—")} tCO2e</span>'
                    f'<span class="ct-re-label">{entry.get("label","—")}</span>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
            with h_col2:
                eid = entry.get("emission_id", "")
                if eid and eid != "—":
                    st.caption(f"`{eid[:8]}…`")


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    "Registro append-only conforme ISAE 3000."
)

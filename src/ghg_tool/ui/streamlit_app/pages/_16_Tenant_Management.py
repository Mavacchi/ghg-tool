"""Gestione Tenant — pagina admin-only per la gestione multi-tenant (wave 4).

RBAC: solo gli utenti con ``role == "admin"`` possono accedere.
Gli altri ruoli vedono un messaggio di accesso negato e la pagina si ferma.

Funzionalità:
  - Tabella tenant esistenti con contatori siti/utenti
  - Form "Crea nuovo tenant" (code + legal_name)
  - Form "Rinomina tenant" (selettore + nuovo code/nome)
  - Form "Disabilita tenant" (selettore + confirm checkbox)

Nessun calcolo di emissioni viene eseguito in questa pagina.
"""

from __future__ import annotations

import re

import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    DASHBOARD_ID,
    DASHBOARD_VERSION,
    PRODUCT_NAME,
    page_icon,
)

st.set_page_config(
    page_title=f"Gestione Tenant · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.brand import (  # noqa: E402
    apply_brand_chrome,
    render_context_bar,
    render_role_chip,
)
from ghg_tool.ui.clients.tenant_admin_client import (  # noqa: E402
    create_tenant,
    deactivate_tenant,
    list_tenants,
    rename_tenant,
)

apply_brand_chrome()
require_auth()
lang = get_lang()

# ---------------------------------------------------------------------------
# RBAC gate — admin only
# ---------------------------------------------------------------------------
role = st.session_state.get("role", "viewer")
if role != "admin":
    st.error(
        "Accesso negato. Questa pagina è riservata agli amministratori di sistema.",
        icon="🔒",
    )
    st.stop()

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
st.title("Gestione Tenant")
render_role_chip(role, lang)
render_context_bar(
    lang=lang,
    year=None,
    gwp=None,
    role=role,
)
st.caption(
    "Crea, rinomina e disabilita i tenant (organizzazioni) registrate nel sistema. "
    "La disabilitazione è sempre reversibile; i dati vengono conservati per conformità CSRD/ISAE-3000."
)

st.warning(
    "Le modifiche ai tenant hanno effetto immediato su tutti gli utenti dell'organizzazione. "
    "Procedi con cautela.",
    icon="⚠️",
)

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,59}$")

# ---------------------------------------------------------------------------
# Helper to explain API errors in IT
# ---------------------------------------------------------------------------


def _explain_err(resp: dict) -> str:  # type: ignore[type-arg]
    sc = resp.get("status_code")
    err = resp.get("error", "errore sconosciuto")
    if sc == 401:
        return "Sessione scaduta o token non valido. Effettua di nuovo l'accesso."
    if sc == 403:
        return "Accesso negato. Solo gli amministratori possono gestire i tenant."
    if sc == 404:
        return "Tenant non trovato. Ricarica la pagina e riprova."
    if sc == 409:
        return f"Codice tenant già in uso: {err}"
    if sc == 422:
        return f"Dati non validi: {err}"
    if sc:
        return f"Errore HTTP {sc}: {err}"
    return f"Errore di rete: {err}"


# ---------------------------------------------------------------------------
# Section 1 — Tenant list
# ---------------------------------------------------------------------------
st.subheader("Tenant registrati")

if st.button("Ricarica elenco", key="tm_refresh"):
    st.session_state.pop("tm_tenants", None)

if "tm_tenants" not in st.session_state:
    with st.spinner("Caricamento tenant..."):
        raw = list_tenants()
    if isinstance(raw, list):
        st.session_state["tm_tenants"] = raw
    else:
        st.error(_explain_err(raw), icon="🚫")
        st.session_state["tm_tenants"] = []

tenants: list[dict] = st.session_state.get("tm_tenants", [])  # type: ignore[type-arg]

if tenants:
    import pandas as pd

    df_tenants = pd.DataFrame([
        {
            "ID": str(t.get("id", "")),
            "Code": t.get("code", ""),
            "Nome legale": t.get("legal_name", ""),
            "Attivo": "Sì" if t.get("is_active") else "No",
            "Creato il": str(t.get("created_at", ""))[:10],
            "Siti": t.get("site_count", 0),
            "Utenti": t.get("user_count", 0),
        }
        for t in tenants
    ])
    st.dataframe(df_tenants, use_container_width=True, hide_index=True)
else:
    st.info("Nessun tenant trovato.", icon="ℹ️")

st.divider()

# ---------------------------------------------------------------------------
# Section 2 — Crea nuovo tenant
# ---------------------------------------------------------------------------
st.subheader("Crea nuovo tenant")
st.caption(
    "Il codice deve essere univoco, composto da lettere maiuscole (A-Z), "
    "cifre (0-9) e underscore (_), iniziare con una lettera maiuscola."
)

with st.form("tm_create_form", clear_on_submit=False):
    _c1, _c2 = st.columns(2)
    with _c1:
        new_code = st.text_input(
            "Codice tenant",
            placeholder="Es. NEW_COMPANY_01",
            max_chars=60,
            help="Univoco. Solo A-Z, 0-9, _. Es: GRESMALT, TILE_CO_EMILIA.",
        )
    with _c2:
        new_name = st.text_input(
            "Nome legale",
            placeholder="Es. Nuova S.p.A.",
            max_chars=200,
        )
    create_submitted = st.form_submit_button("Crea tenant", type="primary")

if create_submitted:
    if not new_code.strip():
        st.error("Il codice tenant è obbligatorio.")
    elif not _CODE_RE.match(new_code.strip()):
        st.error(
            "Codice non valido. Usa solo lettere maiuscole A-Z, cifre 0-9 e "
            "underscore _; deve iniziare con una lettera maiuscola."
        )
    elif not new_name.strip():
        st.error("Il nome legale è obbligatorio.")
    elif not st.session_state.get("_inflight_tm_create"):
        st.session_state["_inflight_tm_create"] = True
        try:
            resp = create_tenant(new_code.strip(), new_name.strip())
        finally:
            st.session_state["_inflight_tm_create"] = False
        if "error" in resp:
            st.error(_explain_err(resp), icon="🚫")
        else:
            new_id = resp.get("id", "")
            st.success(
                f"Tenant **{resp.get('code')}** creato. ID: `{new_id}`",
                icon="✅",
            )
            st.session_state.pop("tm_tenants", None)  # force refresh
            st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Section 3 — Rinomina tenant
# ---------------------------------------------------------------------------
st.subheader("Rinomina tenant")

_active_tenants = [t for t in tenants if t.get("is_active", True)]
if not _active_tenants:
    st.caption("Nessun tenant attivo disponibile.")
else:
    _tenant_opts = {
        f"{t.get('code')} — {t.get('legal_name')}": t.get("id")
        for t in _active_tenants
    }
    with st.form("tm_rename_form", clear_on_submit=False):
        rename_pick = st.selectbox(
            "Tenant da rinominare",
            options=list(_tenant_opts.keys()),
            index=None,
            placeholder="Seleziona un tenant…",
        )
        _r1, _r2 = st.columns(2)
        with _r1:
            rename_code = st.text_input(
                "Nuovo codice (lascia vuoto per non cambiare)",
                max_chars=60,
                placeholder="Es. NUOVA_RAGIONE_SOCIALE",
            )
        with _r2:
            rename_name = st.text_input(
                "Nuovo nome legale (lascia vuoto per non cambiare)",
                max_chars=200,
                placeholder="Es. Nuova Denominazione S.p.A.",
            )
        rename_submitted = st.form_submit_button(
            "Applica rinomina", type="primary", disabled=rename_pick is None
        )

    if rename_submitted and rename_pick is not None:
        tid = _tenant_opts.get(rename_pick)
        if tid is None:
            st.error("Tenant non trovato nell'elenco. Ricarica la pagina.")
        elif rename_code and not _CODE_RE.match(rename_code.strip()):
            st.error(
                "Nuovo codice non valido. Usa solo A-Z, 0-9, _ e inizia con lettera maiuscola."
            )
        elif not rename_code.strip() and not rename_name.strip():
            st.warning("Inserisci almeno un campo da modificare.", icon="⚠️")
        elif not st.session_state.get("_inflight_tm_rename"):
            st.session_state["_inflight_tm_rename"] = True
            try:
                resp = rename_tenant(
                    str(tid),
                    code=rename_code.strip() or None,
                    legal_name=rename_name.strip() or None,
                )
            finally:
                st.session_state["_inflight_tm_rename"] = False
            if "error" in resp:
                st.error(_explain_err(resp), icon="🚫")
            else:
                st.success(
                    f"Tenant aggiornato: **{resp.get('code')}** — {resp.get('legal_name')}",
                    icon="✅",
                )
                st.session_state.pop("tm_tenants", None)
                st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Section 4 — Disabilita tenant
# ---------------------------------------------------------------------------
st.subheader("Disabilita tenant")
st.caption(
    "La disabilitazione è reversibile: imposta ``is_active = FALSE`` ma "
    "non cancella alcun dato. I dati storici rimangono consultabili dagli admin."
)

if not _active_tenants:
    st.caption("Nessun tenant attivo da disabilitare.")
else:
    _dis_opts = {
        f"{t.get('code')} — {t.get('legal_name')}": t.get("id")
        for t in _active_tenants
    }
    with st.form("tm_disable_form", clear_on_submit=True):
        disable_pick = st.selectbox(
            "Tenant da disabilitare",
            options=list(_dis_opts.keys()),
            index=None,
            placeholder="Seleziona un tenant…",
        )
        disable_confirm = st.checkbox(
            "Confermo: voglio disabilitare questo tenant. "
            "Gli utenti non potranno più accedere.",
            value=False,
        )
        disable_submitted = st.form_submit_button(
            "Disabilita tenant",
            type="primary",
            disabled=(disable_pick is None or not disable_confirm),
        )

    if disable_submitted and disable_pick is not None and disable_confirm:
        tid = _dis_opts.get(disable_pick)
        if tid is None:
            st.error("Tenant non trovato nell'elenco. Ricarica la pagina.")
        elif not st.session_state.get("_inflight_tm_disable"):
            st.session_state["_inflight_tm_disable"] = True
            try:
                resp = deactivate_tenant(str(tid))
            finally:
                st.session_state["_inflight_tm_disable"] = False
            if "error" in resp:
                st.error(_explain_err(resp), icon="🚫")
            else:
                st.success(
                    f"Tenant **{resp.get('code')}** disabilitato. "
                    f"{resp.get('detail', '')}",
                    icon="✅",
                )
                st.session_state.pop("tm_tenants", None)
                st.rerun()

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    "Gestione tenant — solo admin."
)

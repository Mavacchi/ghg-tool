"""TOTP 2FA management page -- enrollment, verification, disable.

Flow:
  - If 2FA not enabled: show Enroll button -> QR code -> 6-digit verify form.
  - If 2FA enabled: show current status + Disable form (requires live OTP).
"""

from __future__ import annotations

import base64

import httpx
import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    DASHBOARD_ID,
    DASHBOARD_VERSION,
    PRODUCT_NAME,
    page_icon,
)

st.set_page_config(
    page_title=f"2FA · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="centered",
)

from ghg_tool.ui.streamlit_app.lib.auth import (  # noqa: E402
    get_lang,
    get_token,
    require_auth,
)
from ghg_tool.ui.streamlit_app.lib.brand import (  # noqa: E402
    apply_brand_chrome,
    render_context_bar,
    render_role_chip,
)

apply_brand_chrome()
require_auth()
lang = get_lang()

render_role_chip(st.session_state.get("role"), lang)

st.title("Autenticazione a due fattori (2FA)")
st.caption(
    "Proteggi il tuo account con un codice TOTP generato da un'app come "
    "Google Authenticator o Authy (RFC 6238)."
)

render_context_bar(lang=lang, year=None, gwp=None, role=st.session_state.get("role"))

api_base = st.session_state.get("api_base_url", "http://localhost:8000")
token = get_token() or ""
_HEADERS = {"Authorization": f"Bearer {token}"}


def _enroll() -> dict | None:
    try:
        resp = httpx.post(
            f"{api_base}/api/v1/auth/totp/enroll",
            headers=_HEADERS,
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:  # noqa: BLE001
        pass
    return None


def _verify(otp: str) -> bool:
    try:
        resp = httpx.post(
            f"{api_base}/api/v1/auth/totp/verify",
            json={"otp": otp},
            headers=_HEADERS,
            timeout=10.0,
        )
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _disable(otp: str) -> bool:
    try:
        resp = httpx.post(
            f"{api_base}/api/v1/auth/totp/disable",
            json={"otp": otp},
            headers=_HEADERS,
            timeout=10.0,
        )
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------
if "totp_enroll_data" not in st.session_state:
    st.session_state["totp_enroll_data"] = None  # dict with secret_b32, qr_png_b64

# We derive 2FA status from what we know locally; a real implementation
# would call GET /api/v1/users/me but that endpoint is out of scope here.
totp_enabled: bool = st.session_state.get("totp_enabled_flag", False)
enroll_data = st.session_state.get("totp_enroll_data")

st.divider()

# ---------------------------------------------------------------------------
# If 2FA is enabled: show status + disable form
# ---------------------------------------------------------------------------
if totp_enabled:
    st.success("2FA attivo sul tuo account.")
    st.markdown("#### Disabilita 2FA")
    st.caption("Inserisci il codice OTP corrente per disabilitare la protezione 2FA.")

    with st.form("disable_form"):
        otp_input = st.text_input(
            "Codice OTP (6 cifre)",
            max_chars=8,
            placeholder="123456",
            autocomplete="one-time-code",
        )
        submitted = st.form_submit_button("Disabilita 2FA", type="secondary")

    if submitted:
        if not otp_input.strip().isdigit() or len(otp_input.strip()) < 6:
            st.error("Inserisci un codice OTP valido (6 cifre).")
        elif _disable(otp_input.strip()):
            st.success("2FA disabilitato con successo.")
            st.session_state["totp_enabled_flag"] = False
            st.session_state["totp_enroll_data"] = None
            st.rerun()
        else:
            st.error("Codice OTP non valido. Riprova.")

# ---------------------------------------------------------------------------
# If enrollment just completed (QR visible, waiting for verify)
# ---------------------------------------------------------------------------
elif enroll_data is not None:
    st.info("Scansiona il QR code con la tua app TOTP, poi inserisci il codice generato.")

    qr_bytes = base64.b64decode(enroll_data["qr_png_b64"])
    st.image(qr_bytes, caption="QR Code per Google Authenticator / Authy", width=260)

    with st.expander("Inserimento manuale (chiave segreta)"):
        st.code(enroll_data["secret_b32"], language="text")
        st.caption(
            "Copia questa chiave nella tua app TOTP se non riesci a scansionare il QR. "
            "Non condividere mai questa chiave con nessuno."
        )

    st.markdown("#### Verifica codice OTP")
    with st.form("verify_form"):
        otp_input = st.text_input(
            "Codice OTP (6 cifre)",
            max_chars=8,
            placeholder="123456",
            autocomplete="one-time-code",
        )
        submitted = st.form_submit_button("Attiva 2FA", type="primary")

    if submitted:
        if not otp_input.strip().isdigit() or len(otp_input.strip()) < 6:
            st.error("Inserisci un codice OTP valido (6 cifre).")
        elif _verify(otp_input.strip()):
            st.success("2FA attivato con successo! Il tuo account e ora protetto.")
            st.session_state["totp_enabled_flag"] = True
            st.session_state["totp_enroll_data"] = None
            st.rerun()
        else:
            st.error("Codice OTP non valido. Assicurati che l'orario del dispositivo sia sincronizzato.")

    if st.button("Annulla enrollment"):
        st.session_state["totp_enroll_data"] = None
        st.rerun()

# ---------------------------------------------------------------------------
# Enrollment not started: show Enroll button
# ---------------------------------------------------------------------------
else:
    st.info("Il tuo account non ha ancora la 2FA attiva.")
    st.markdown("#### Attiva la protezione 2FA")
    st.markdown(
        "Clicca su **Inizia enrollment** per generare un nuovo segreto TOTP. "
        "Ti verra mostrato un QR code da scansionare con Google Authenticator o Authy."
    )

    if st.button("Inizia enrollment", type="primary"):
        data = _enroll()
        if data:
            st.session_state["totp_enroll_data"] = data
            st.rerun()
        else:
            st.error(
                "Impossibile avviare l'enrollment. "
                "Verifica di essere autenticato e riprova."
            )

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION}")

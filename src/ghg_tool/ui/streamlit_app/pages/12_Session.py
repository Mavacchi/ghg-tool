"""Session page v2 -- JWT info + active sessions list + revoke controls.

Sections:
  1. JWT info (sub, role, tenant, jti, iat, exp) -- kept from v1
  2. Active sessions table (device hint, IP, last seen, current badge)
  3. Revoke-session buttons per row (disabled on current)
  4. Revoke-all-other-sessions button with confirm modal
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import httpx
import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    DASHBOARD_ID,
    DASHBOARD_VERSION,
    PRODUCT_NAME,
    page_icon,
)

st.set_page_config(
    page_title=f"Sessione · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

from ghg_tool.ui.streamlit_app.lib.auth import (  # noqa: E402
    get_lang,
    get_token,
    logout,
    require_auth,
)
from ghg_tool.ui.streamlit_app.lib.brand import (  # noqa: E402
    apply_brand_chrome,
    render_context_bar,
    render_role_chip,
)
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402

apply_brand_chrome()
require_auth()
lang = get_lang()

render_role_chip(st.session_state.get("role"), lang)

st.title(_("session_title", lang))

render_context_bar(
    lang=lang,
    year=None,
    gwp=None,
    role=st.session_state.get("role"),
)

st.caption(_("session_caption", lang))


def _decode_jwt_payload(token: str) -> dict[str, object]:
    """Return the unverified JWT payload claims, or {} on parse failure."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload_b64 = parts[1]
        padding = "=" * (-len(payload_b64) % 4)
        payload = base64.urlsafe_b64decode(payload_b64 + padding)
        decoded = json.loads(payload)
        return decoded if isinstance(decoded, dict) else {}
    except (ValueError, TypeError, json.JSONDecodeError):
        return {}


token = get_token() or ""
claims = _decode_jwt_payload(token)


def _fmt_ts(ts: object) -> str:
    """Format a unix epoch second to ISO-8601 UTC, or return '-'."""
    if not isinstance(ts, int | float):
        return "-"
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Section 1: JWT info
# ---------------------------------------------------------------------------
st.markdown("### " + _("session_jwt_info", lang) if True else "### JWT Info")

col_a, col_b = st.columns(2)
with col_a:
    st.metric(_("session_role", lang), claims.get("role", "?"))
    st.metric(_("session_tenant", lang), str(claims.get("tenant_id", "?"))[:8] + "...")
    st.metric(_("session_jti", lang), str(claims.get("jti", "?"))[:12] or "-")
with col_b:
    st.metric(_("session_issued_at", lang), _fmt_ts(claims.get("iat")))
    st.metric(_("session_expires_at", lang), _fmt_ts(claims.get("exp")))
    st.metric(_("session_sub", lang), str(claims.get("sub", "?"))[:8] + "...")

st.divider()

# ---------------------------------------------------------------------------
# Section 2 + 3: Active sessions list + per-row revoke
# ---------------------------------------------------------------------------
st.markdown("### Sessioni attive")

api_base = st.session_state.get("api_base_url", "http://localhost:8000")
current_jti = str(claims.get("jti", ""))


def _ua_hint(ua: str | None) -> str:
    """Extract a short device hint from User-Agent string."""
    if not ua:
        return "Dispositivo sconosciuto"
    ua_lower = ua.lower()
    if "mobile" in ua_lower or "android" in ua_lower or "iphone" in ua_lower:
        return "Mobile"
    if "chrome" in ua_lower:
        return "Chrome"
    if "firefox" in ua_lower:
        return "Firefox"
    if "safari" in ua_lower:
        return "Safari"
    if "python" in ua_lower or "httpx" in ua_lower:
        return "API Client"
    return ua[:30]


def _load_sessions() -> list[dict]:
    if not token:
        return []
    try:
        resp = httpx.get(
            f"{api_base}/api/v1/auth/sessions/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8.0,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:  # noqa: BLE001
        pass
    return []


def _revoke_session(session_id: str) -> bool:
    try:
        resp = httpx.delete(
            f"{api_base}/api/v1/auth/sessions/{session_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8.0,
        )
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _revoke_all() -> bool:
    try:
        resp = httpx.delete(
            f"{api_base}/api/v1/auth/sessions/all",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8.0,
        )
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


if "sessions_data" not in st.session_state:
    st.session_state["sessions_data"] = _load_sessions()

sessions_data = st.session_state.get("sessions_data", [])

if not sessions_data:
    st.info("Nessuna sessione attiva trovata o sessioni non disponibili.")
else:
    for sess in sessions_data:
        sid = sess.get("id", "")
        is_current = sess.get("is_current", False)
        ua_hint = _ua_hint(sess.get("user_agent"))
        ip = sess.get("ip_address") or "-"
        last_seen_raw = sess.get("last_seen_at", "")
        created_raw = sess.get("created_at", "")

        badge = " **[CORRENTE]**" if is_current else ""
        label = f"{ua_hint} | IP: {ip} | Ultima attivita: {last_seen_raw[:19]}{badge}"

        col_info, col_btn = st.columns([5, 1])
        with col_info:
            st.markdown(label)
        with col_btn:
            if is_current:
                st.button("Revoca", key=f"rev_{sid}", disabled=True)
            else:
                if st.button("Revoca", key=f"rev_{sid}"):
                    if _revoke_session(sid):
                        st.success(f"Sessione {sid[:8]}... revocata.")
                        st.session_state["sessions_data"] = _load_sessions()
                        st.rerun()
                    else:
                        st.error("Impossibile revocare la sessione.")

    if st.button("Aggiorna lista sessioni"):
        st.session_state["sessions_data"] = _load_sessions()
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Section 4: Revoke all other sessions
# ---------------------------------------------------------------------------
st.markdown("### Revoca tutte le altre sessioni")
st.caption(
    "Revoca tutte le sessioni attive tranne quella corrente. "
    "Utile in caso di sospetta compromissione dell'account."
)

if "confirm_revoke_all" not in st.session_state:
    st.session_state["confirm_revoke_all"] = False

if not st.session_state["confirm_revoke_all"]:
    if st.button("Revoca tutte le altre sessioni", type="secondary"):
        st.session_state["confirm_revoke_all"] = True
        st.rerun()
else:
    st.warning("Sei sicuro? Tutte le altre sessioni verranno chiuse immediatamente.")
    col_y, col_n = st.columns(2)
    with col_y:
        if st.button("Si, revoca tutte", type="primary"):
            if _revoke_all():
                st.success("Tutte le altre sessioni sono state revocate.")
            else:
                st.error("Errore durante la revoca delle sessioni.")
            st.session_state["confirm_revoke_all"] = False
            st.session_state["sessions_data"] = _load_sessions()
            st.rerun()
    with col_n:
        if st.button("Annulla"):
            st.session_state["confirm_revoke_all"] = False
            st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Logout + advanced section (kept from v1)
# ---------------------------------------------------------------------------
st.markdown("### " + _("session_actions", lang))

col_l, col_r = st.columns([1, 3])
with col_l:
    if st.button(_("session_logout", lang), type="primary"):
        logout()
        st.rerun()
with col_r:
    st.caption(_("session_logout_help", lang))

st.divider()

with st.expander(_("session_advanced", lang)):
    st.caption(_("session_advanced_caption", lang))
    if token:
        st.code(token[:30] + "..." + token[-10:], language="text")
    else:
        st.caption("(no token in session_state)")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION}"
)

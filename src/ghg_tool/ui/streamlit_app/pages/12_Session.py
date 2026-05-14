"""Session info + logout page.

Carbontrace uses stateless JWTs (no server-side session store yet),
so this page surfaces what we DO know about the current session:
  - decoded JWT claims (sub, role, tenant_id, jti)
  - issued-at and expiry timestamps
  - "Esci" button (also reachable from the Home sidebar)

It also exposes a "Force re-login" action so the user can drop the
in-memory token even when the JWT hasn't expired yet. A future
v2 will add a real session store + active-session list + remote
revoke; the UI scaffold here is ready for that without redesign.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

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
    st.markdown(_("session_v2_note", lang))

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION}"
)

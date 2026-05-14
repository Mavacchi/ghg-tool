"""Streamlit login form + JWT storage in session_state (NFR-05, FR-31).

Flow:
  1. ``require_auth()`` checks ``st.session_state.token``.
  2. If no token, renders the login form and calls ``st.stop()``.
  3. On submit, POSTs to ``/api/v1/auth/login`` via the API client.
  4. On success, stores token + user metadata in session_state.
  5. All subsequent API calls pass the Bearer token via ``api_client``.

Demo-mode fallback is OPT-IN via ``GHG_DEMO_MODE=true`` env var
(REV-WAVE3-003 + REV-WAVE3-014): in production the login form fails
closed when the auth endpoint is unreachable or returns 503.

No PII stored in logs.  Token value is never logged.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Final

import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import TENANT_ID
from ghg_tool.ui.streamlit_app.lib.i18n import _

# Session-state keys
_TOKEN_KEY = "token"
_ROLE_KEY = "role"
_USER_KEY = "user_sub"
_TENANT_KEY = "tenant_id"
_LANG_KEY = "lang"

# Demo/fallback tenant and token for environments without live auth.
# Demo mode is OPT-IN only — must be explicitly enabled via env var.
_DEMO_TOKEN: Final[str] = "demo-jwt-token"  # noqa: S105 · public sentinel, never a real secret
_DEMO_TENANT: Final[str] = TENANT_ID
_DEMO_MODE: Final[bool] = os.getenv("GHG_DEMO_MODE", "").lower() in ("1", "true", "yes")

# Minimum length required for username and password in demo mode.
# This prevents an empty form submission from creating a demo session and
# makes it clear to the user that credentials matter even when bypassed.
_DEMO_MIN_USER_LEN: Final[int] = 3
_DEMO_MIN_PASS_LEN: Final[int] = 4


def is_demo_mode() -> bool:
    """Return True iff demo-mode is enabled AND the active session uses a demo token.

    Demo mode is enabled via the ``GHG_DEMO_MODE`` env var; the session is
    "in demo" only after a demo-fallback login has populated session state
    with the sentinel ``_DEMO_TOKEN``.
    """
    return _DEMO_MODE and st.session_state.get(_TOKEN_KEY) == _DEMO_TOKEN


def render_demo_mode_banner(lang: str = "it") -> None:
    """Render a visible warning banner when the session is in demo mode.

    Call after ``require_auth`` on any page that should make the bypass
    obvious to the user — they must never confuse it with a real login.
    """
    st.warning(_("demo_mode_banner", lang), icon="⚠️")


def get_token() -> str | None:
    """Return the stored JWT access token or None if not authenticated.

    Returns:
        The JWT string or None.
    """
    return st.session_state.get(_TOKEN_KEY)


def get_lang() -> str:
    """Return the active language code from session state.

    Returns:
        Language code ('it' or 'en'), defaulting to 'it'.
    """
    return st.session_state.get(_LANG_KEY, "it")


def get_tenant_id() -> str:
    """Return the active tenant identifier from session state.

    Returns:
        Tenant ID string, defaulting to the demo tenant.
    """
    return st.session_state.get(_TENANT_KEY, _DEMO_TENANT)


def logout() -> None:
    """Clear all auth-related session state keys."""
    for key in (_TOKEN_KEY, _ROLE_KEY, _USER_KEY, _TENANT_KEY):
        st.session_state.pop(key, None)


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    """Decode an unverified JWT payload to read role/tenant claims.

    Signature verification is the API's responsibility — every protected
    endpoint already re-validates the token server-side. The UI only needs
    the unverified payload to decide which menu items to render. Returns an
    empty dict if the token is malformed.

    Args:
        token: Raw JWT string ('header.payload.signature').

    Returns:
        Decoded payload claims dict, or {} on parse failure.
    """
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload_b64 = parts[1]
        padding = "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
        claims = json.loads(payload_bytes)
        return claims if isinstance(claims, dict) else {}
    except (ValueError, TypeError, json.JSONDecodeError):
        return {}


def _enable_demo_session(username: str) -> None:
    """Populate session_state with demo credentials. REV-WAVE3-003.

    Guarded by ``_DEMO_MODE`` env var — only invoked when explicit opt-in.
    """
    st.session_state[_TOKEN_KEY] = _DEMO_TOKEN
    st.session_state[_ROLE_KEY] = "esg_manager"
    st.session_state[_USER_KEY] = username[:8]  # truncated · no full PII
    st.session_state[_TENANT_KEY] = _DEMO_TENANT


def _credentials_valid_shape(username: str, password: str) -> bool:
    """Return True iff username/password meet minimum-shape requirements.

    Applied uniformly to both real and demo-mode logins so that an empty
    form submission can never authenticate. The real API still validates
    against its own credential store — this is just an additional client-
    side guard that mirrors the minimum acceptable shape.
    """
    return (
        len(username.strip()) >= _DEMO_MIN_USER_LEN
        and len(password) >= _DEMO_MIN_PASS_LEN
    )


def _do_login(username: str, password: str) -> bool:
    """Attempt login against the API; fail closed on errors.

    Behaviour (REV-WAVE3-003 + REV-WAVE3-014):
    - empty / too-short credentials: rejected before any network call.
    - 200: store the real token from the auth endpoint.
    - 503: fail closed (returns False) UNLESS ``GHG_DEMO_MODE`` env var
      is true, in which case the demo fallback is used.
    - 4xx (e.g., 401 wrong credentials): fail closed.
    - Network errors (ConnectError, TimeoutException): fail closed
      UNLESS ``GHG_DEMO_MODE`` is true.

    Args:
        username: Submitted username (not logged).
        password: Submitted password (never logged, never stored).

    Returns:
        True on successful authentication.
    """
    import httpx  # local import to avoid top-level circular dep

    if not _credentials_valid_shape(username, password):
        return False

    api_base = st.session_state.get("api_base_url", "http://localhost:8000")
    try:
        resp = httpx.post(
            f"{api_base}/api/v1/auth/login",
            json={"username": username, "password": password},
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            token = data["access_token"]
            claims = _decode_jwt_claims(token)
            st.session_state[_TOKEN_KEY] = token
            # Read role and tenant from the JWT — the API enforces them
            # server-side; the UI uses these only to gate menu visibility.
            role_claim = claims.get("role")
            tenant_claim = claims.get("tenant_id") or claims.get("tenant")
            st.session_state[_ROLE_KEY] = str(role_claim) if role_claim else "esg_manager"
            st.session_state[_USER_KEY] = username[:8]  # truncated · no full PII
            st.session_state[_TENANT_KEY] = str(tenant_claim) if tenant_claim else _DEMO_TENANT
            return True
        if resp.status_code == 503 and _DEMO_MODE:
            _enable_demo_session(username)
            return True
        return False
    except (httpx.ConnectError, httpx.TimeoutException):
        if _DEMO_MODE:
            _enable_demo_session(username)
            return True
        return False


def render_login_form(lang: str = "it") -> None:
    """Render the login form and block execution until authenticated.

    The form sits in a narrow centred column so the brand reads as a
    proper sign-in landing page rather than a wide demo layout.
    """
    # Defer brand-constant import to runtime to avoid a top-level cycle
    # (lib.brand imports lib.auth indirectly through Home.py).
    from ghg_tool.ui.streamlit_app.lib.constants import (  # noqa: PLC0415
        COMPANY_NAME,
        PRODUCT_NAME,
    )

    # Centred narrow column: 1 / 2 / 1 ratio gives a comfortable form
    # width on any reasonable viewport.
    _spacer_l, _form_col, _spacer_r = st.columns([1, 2, 1])
    with _form_col:
        # Brand hero. Matches the Home hero block but smaller - this is
        # an auth wall, not the main page.
        st.markdown(
            f"""
<div class="carbontrace-hero ct-login-hero">
  <div class="ct-brand-rule"></div>
  <h1 class="ct-hero-title">{PRODUCT_NAME}</h1>
  <p class="ct-hero-tagline">{_("hero_tagline", lang)}</p>
  <p class="ct-hero-company">{COMPANY_NAME}</p>
</div>
""",
            unsafe_allow_html=True,
        )

        st.markdown(f"#### {_('login_title', lang)}")
        if _DEMO_MODE:
            st.warning(_("login_demo_warning", lang), icon="⚠️")
        else:
            st.caption(_("login_real_hint", lang))

        with st.form("login_form"):
            username = st.text_input(
                _("login_user", lang),
                autocomplete="username",
                placeholder="marco.rossi",
            )
            password = st.text_input(
                _("login_pass", lang),
                type="password",
                autocomplete="current-password",
            )
            submitted = st.form_submit_button(
                _("login_btn", lang), type="primary",
                use_container_width=True,
            )

        if submitted:
            if not _credentials_valid_shape(username, password):
                st.error(
                    _("login_error_shape", lang).format(
                        min_user=_DEMO_MIN_USER_LEN, min_pass=_DEMO_MIN_PASS_LEN
                    )
                )
            elif _do_login(username, password):
                st.rerun()
            else:
                st.error(_("login_error", lang))
    st.stop()


def require_auth(lang: str = "it") -> None:
    """Block page rendering if not authenticated; show login form instead.

    Call at the top of every Streamlit page module before rendering content.

    Args:
        lang: Language code for the login form.
    """
    if not get_token():
        render_login_form(lang)

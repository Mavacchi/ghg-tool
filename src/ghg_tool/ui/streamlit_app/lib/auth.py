"""Streamlit login form + JWT storage in session_state (NFR-05, FR-31).

Flow:
  1. ``require_auth()`` checks ``st.session_state.token``.
  2. If no token, renders the login form and calls ``st.stop()``.
  3. On submit, POSTs to ``/api/v1/auth/login`` via the API client.
  4. On success, stores token + user metadata in session_state.
  5. All subsequent API calls pass the Bearer token via ``api_client``.

No PII stored in logs.  Token value is never logged.
"""

from __future__ import annotations

import streamlit as st

from ghg_tool.ui.streamlit_app.lib.i18n import _

# Session-state keys
_TOKEN_KEY = "token"
_ROLE_KEY = "role"
_USER_KEY = "user_sub"
_TENANT_KEY = "tenant_id"
_LANG_KEY = "lang"

# Demo/fallback tenant and token for environments without live auth
_DEMO_TOKEN = "demo-jwt-token"  # noqa: S105 — not a real secret
_DEMO_TENANT = "saturnia-ceramica-v1"


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


def _do_login(username: str, password: str) -> bool:
    """Attempt login against the API; fall back to demo token on 503.

    Args:
        username: Submitted username (not logged).
        password: Submitted password (never logged, never stored).

    Returns:
        True on successful authentication (real or demo fallback).
    """
    import httpx  # local import to avoid top-level circular dep

    api_base = st.session_state.get("api_base_url", "http://localhost:8000")
    try:
        resp = httpx.post(
            f"{api_base}/api/v1/auth/login",
            json={"username": username, "password": password},
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            st.session_state[_TOKEN_KEY] = data["access_token"]
            st.session_state[_ROLE_KEY] = "esg_manager"  # decoded from JWT in prod
            st.session_state[_USER_KEY] = username[:8]  # truncated — no full PII
            st.session_state[_TENANT_KEY] = _DEMO_TENANT
            return True
        if resp.status_code == 503:
            # Wave-3 fallback: auth endpoint not yet wired to user DB
            st.session_state[_TOKEN_KEY] = _DEMO_TOKEN
            st.session_state[_ROLE_KEY] = "esg_manager"
            st.session_state[_USER_KEY] = username[:8]
            st.session_state[_TENANT_KEY] = _DEMO_TENANT
            return True
        return False
    except (httpx.ConnectError, httpx.TimeoutException):
        # API not reachable — enter demo mode so the UI is still usable
        st.session_state[_TOKEN_KEY] = _DEMO_TOKEN
        st.session_state[_ROLE_KEY] = "esg_manager"
        st.session_state[_USER_KEY] = username[:8]
        st.session_state[_TENANT_KEY] = _DEMO_TENANT
        return True


def render_login_form(lang: str = "it") -> None:
    """Render the login form and block execution until authenticated.

    Args:
        lang: Language code for labels.
    """
    st.title(_("login_title", lang))
    st.caption(_("login_demo_hint", lang))

    with st.form("login_form"):
        username = st.text_input(_("login_user", lang))
        password = st.text_input(_("login_pass", lang), type="password")
        submitted = st.form_submit_button(_("login_btn", lang))

    if submitted:
        if _do_login(username, password):
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

"""Admin page - user management (esg_manager only).

The third tier of the role hierarchy ("Administrator") gets a dedicated
page for the only operation that today requires admin privileges:
managing the users of the tenant. The page calls the ``/api/v1/users``
router landed in this PR; the data_steward and auditor tiers see a clear
"403-like" notice rather than the form so they understand the gate.

Future expansions (out of scope for this PR but easy hook points here):
  - Disable / reactivate users.
  - Change role assignment.
  - Reset password.
  - Site / sub-organisation management.
"""

from __future__ import annotations

import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    DASHBOARD_ID,
    DASHBOARD_VERSION,
    PRODUCT_NAME,
    page_icon,
)

st.set_page_config(
    page_title=f"Admin · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

from ghg_tool.ui.streamlit_app.lib.api_client import create_user, list_users  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.privacy import render_privacy_notice  # noqa: E402
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

st.title(_("nav_admin", lang))

render_context_bar(
    lang=lang,
    year=None,
    gwp=None,
    role=st.session_state.get("role"),
)

_role = st.session_state.get("role", "viewer")
if _role != "admin":
    st.warning(_("admin_role_required", lang), icon="🔒")
    st.stop()

st.caption(_("admin_intro", lang))

# ---------------------------------------------------------------------------
# Existing users
# ---------------------------------------------------------------------------
st.subheader(_("admin_users_existing", lang))

users_raw = list_users()
if isinstance(users_raw, dict) and "error" in users_raw:
    sc = users_raw.get("status_code")
    if sc == 403:
        st.error(_("admin_role_required", lang))
    else:
        st.error(f"HTTP {sc}: {users_raw.get('error', '?')}")
    users: list[dict] = []
elif isinstance(users_raw, list):
    users = users_raw
else:
    users = []

if not users:
    st.info(_("admin_users_empty", lang))
else:
    import pandas as pd  # noqa: PLC0415

    df = pd.DataFrame(users)
    # Friendly column ordering + renaming for IT/EN.
    cols = ["username", "email", "role_code", "is_active"]
    df = df[[c for c in cols if c in df.columns]]
    df.columns = [_("admin_col_" + c, lang) for c in df.columns]
    st.dataframe(df, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Create user
# ---------------------------------------------------------------------------
st.subheader(_("admin_users_create", lang))
st.caption(_("admin_users_create_caption", lang))

# GDPR Art. 13 notice — shown to the admin who creates users on their behalf
# so they are informed of the data processing obligations for newly created
# accounts (F-14).
render_privacy_notice(lang=lang)

with st.form("admin_create_user", clear_on_submit=True):
    cols = st.columns([1, 1])
    with cols[0]:
        new_username = st.text_input(
            _("admin_field_username", lang),
            max_chars=120,
            placeholder="marco.rossi",
            autocomplete="off",
        )
        new_email = st.text_input(
            _("admin_field_email", lang),
            max_chars=200,
            placeholder="marco.rossi@gresmalt.it",
            autocomplete="off",
        )
    with cols[1]:
        new_role = st.selectbox(
            _("admin_field_role", lang),
            ("editor", "admin", "viewer"),
            format_func=lambda r: _("admin_role_" + r, lang),
        )
        new_password = st.text_input(
            _("admin_field_password", lang),
            type="password",
            max_chars=200,
            help=_("admin_password_hint", lang),
        )

    submitted = st.form_submit_button(
        _("admin_create_btn", lang),
        type="primary",
        disabled=st.session_state.get("_inflight_create_user", False),
    )

if submitted:
    if (
        len(new_username.strip()) < 3
        or "@" not in new_email
        or len(new_password) < 8
    ):
        st.error(_("admin_validation_failed", lang))
    else:
        st.session_state["_inflight_create_user"] = True
        try:
            resp = create_user(
                username=new_username.strip(),
                email=new_email.strip(),
                role_code=new_role,
                password=new_password,
            )
        finally:
            st.session_state["_inflight_create_user"] = False
        if "error" in resp:
            sc = resp.get("status_code")
            if sc == 409:
                st.error(_("admin_duplicate", lang))
            elif sc == 422:
                st.error(_("admin_validation_failed", lang))
            elif sc == 403:
                st.error(_("admin_role_required", lang))
            else:
                st.error(f"HTTP {sc}: {resp.get('error', '?')}")
        else:
            st.success(_("admin_user_created", lang))
            # Force a rerun so the new row appears in the existing list.
            st.rerun()

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    f"{_('admin_audit_note', lang)}"
)

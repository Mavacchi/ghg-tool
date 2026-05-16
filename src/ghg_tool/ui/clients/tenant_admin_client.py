"""HTTP client for admin tenant management endpoints.

Wraps:
  GET    /api/v1/admin/tenants          — list tenants
  POST   /api/v1/admin/tenants          — create tenant
  PATCH  /api/v1/admin/tenants/{id}     — rename tenant
  DELETE /api/v1/admin/tenants/{id}     — deactivate tenant

All endpoints require ``role == "admin"``.  No GHG calculations here.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

from ghg_tool.ui.clients._http_client import safe_request

_DEFAULT_BASE_URL = os.environ.get("GHG_API_BASE_URL", "http://localhost:8000")
_TIMEOUT = 30.0
_API_PREFIX = "/api/v1/admin/tenants"


def _get_base_url() -> str:
    return st.session_state.get("api_base_url", _DEFAULT_BASE_URL)


def _get_auth_headers() -> dict[str, str]:
    from ghg_tool.ui.streamlit_app.lib.auth import _DEMO_MODE, _DEMO_TOKEN  # noqa: PLC0415

    token = st.session_state.get("token")
    if not token:
        token = _DEMO_TOKEN if _DEMO_MODE else None
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _safe_get(url: str) -> dict[str, Any]:
    return safe_request(
        "GET", url, headers=_get_auth_headers(), timeout=_TIMEOUT, _httpx=httpx
    )


def _safe_post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    return safe_request(
        "POST", url, headers=_get_auth_headers(), body=body, timeout=_TIMEOUT, _httpx=httpx
    )


def _safe_patch(url: str, body: dict[str, Any]) -> dict[str, Any]:
    return safe_request(
        "PATCH", url, headers=_get_auth_headers(), body=body, timeout=_TIMEOUT, _httpx=httpx
    )


def _safe_delete(url: str) -> dict[str, Any]:
    return safe_request(
        "DELETE", url, headers=_get_auth_headers(), timeout=_TIMEOUT, _httpx=httpx
    )


def list_tenants() -> list[dict[str, Any]] | dict[str, Any]:
    """GET /api/v1/admin/tenants.

    Returns:
        List of tenant dicts on success, or error dict on failure.
    """
    raw = _safe_get(f"{_get_base_url()}{_API_PREFIX}")
    if isinstance(raw, list):
        return raw
    return raw  # error dict


def create_tenant(code: str, legal_name: str) -> dict[str, Any]:
    """POST /api/v1/admin/tenants — create a new tenant.

    Args:
        code: Unique uppercase tenant code.
        legal_name: Legal name of the tenant.

    Returns:
        TenantCreateResponse dict or error dict.
    """
    return _safe_post(
        f"{_get_base_url()}{_API_PREFIX}",
        body={"code": code, "legal_name": legal_name},
    )


def rename_tenant(
    tenant_id: str,
    *,
    code: str | None = None,
    legal_name: str | None = None,
) -> dict[str, Any]:
    """PATCH /api/v1/admin/tenants/{id} — rename a tenant.

    Args:
        tenant_id: UUID string of the tenant to rename.
        code: New code (optional).
        legal_name: New legal name (optional).

    Returns:
        Updated TenantListItem dict or error dict.
    """
    body: dict[str, Any] = {}
    if code is not None:
        body["code"] = code
    if legal_name is not None:
        body["legal_name"] = legal_name
    return _safe_patch(
        f"{_get_base_url()}{_API_PREFIX}/{tenant_id}",
        body=body,
    )


def deactivate_tenant(tenant_id: str) -> dict[str, Any]:
    """DELETE /api/v1/admin/tenants/{id} — soft-deactivate a tenant.

    Note: this performs a soft deactivation (``is_active = FALSE``), not a
    hard delete.  Data is retained for CSRD/ISAE-3000 compliance.

    Args:
        tenant_id: UUID string of the tenant to deactivate.

    Returns:
        TenantDeactivateResponse dict or error dict.
    """
    return _safe_delete(
        f"{_get_base_url()}{_API_PREFIX}/{tenant_id}"
    )

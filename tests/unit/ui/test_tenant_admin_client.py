"""Coverage tests for ``ghg_tool.ui.clients.tenant_admin_client``.

Uses ``unittest.mock.patch`` on ``httpx.{get,post,patch,delete}`` directly
(no respx dependency), matching the pattern used by ``test_sites_client.py``.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

# Module eviction (mirrors test_sites_client.py): prevent stale copies.
for _mod in (
    "ghg_tool.ui.clients.tenant_admin_client",
    "ghg_tool.ui.clients",
):
    sys.modules.pop(_mod, None)

from ghg_tool.ui.clients import tenant_admin_client as tac  # noqa: E402

_BASE = "http://api.test"
_PREFIX = "/api/v1/admin/tenants"
_PATCH_BASE = "ghg_tool.ui.clients.tenant_admin_client._get_base_url"
_PATCH_HEADERS = "ghg_tool.ui.clients.tenant_admin_client._get_auth_headers"


def _make_resp(status_code: int, json_body: Any) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body
    if status_code >= 400:
        err = httpx.HTTPStatusError(
            "err", request=MagicMock(spec=httpx.Request), response=resp
        )
        resp.raise_for_status.side_effect = err
    else:
        resp.raise_for_status.return_value = None
    return resp


@pytest.fixture(autouse=True)
def _stub_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tac, "_get_base_url", lambda: _BASE)
    monkeypatch.setattr(tac, "_get_auth_headers", lambda: {"Authorization": "Bearer x"})


def test_list_tenants_success() -> None:
    payload: list[dict[str, Any]] = [{"id": "t1", "code": "ACME", "is_active": True}]
    with patch("ghg_tool.ui.clients.tenant_admin_client.httpx.get") as mget:
        mget.return_value = _make_resp(200, payload)
        result = tac.list_tenants()
    assert result == payload
    mget.assert_called_once()
    assert mget.call_args.args[0] == f"{_BASE}{_PREFIX}"


def test_list_tenants_http_error() -> None:
    with patch("ghg_tool.ui.clients.tenant_admin_client.httpx.get") as mget:
        mget.return_value = _make_resp(403, {"detail": "forbidden"})
        result = tac.list_tenants()
    assert isinstance(result, dict)
    assert result["status_code"] == 403


def test_list_tenants_network_error() -> None:
    with patch("ghg_tool.ui.clients.tenant_admin_client.httpx.get") as mget:
        mget.side_effect = httpx.ConnectError("boom")
        result = tac.list_tenants()
    assert isinstance(result, dict)
    assert "error" in result


def test_create_tenant_success() -> None:
    body = {"id": "t2", "code": "BETA", "legal_name": "Beta Srl"}
    with patch("ghg_tool.ui.clients.tenant_admin_client.httpx.post") as mpost:
        mpost.return_value = _make_resp(201, body)
        result = tac.create_tenant(code="BETA", legal_name="Beta Srl")
    assert result == body
    assert mpost.call_args.kwargs["json"] == {"code": "BETA", "legal_name": "Beta Srl"}


def test_create_tenant_http_error() -> None:
    with patch("ghg_tool.ui.clients.tenant_admin_client.httpx.post") as mpost:
        mpost.return_value = _make_resp(409, {"detail": "exists"})
        result = tac.create_tenant(code="DUP", legal_name="Dup")
    assert result["status_code"] == 409


def test_create_tenant_network_error() -> None:
    with patch("ghg_tool.ui.clients.tenant_admin_client.httpx.post") as mpost:
        mpost.side_effect = httpx.ConnectError("nope")
        result = tac.create_tenant(code="X", legal_name="X")
    assert "error" in result


def test_rename_tenant_partial_payload() -> None:
    with patch("ghg_tool.ui.clients.tenant_admin_client.httpx.patch") as mpatch:
        mpatch.return_value = _make_resp(200, {"id": "abc", "code": "NEW"})
        result = tac.rename_tenant("abc", code="NEW")
    assert result["code"] == "NEW"
    assert mpatch.call_args.kwargs["json"] == {"code": "NEW"}


def test_rename_tenant_both_fields() -> None:
    with patch("ghg_tool.ui.clients.tenant_admin_client.httpx.patch") as mpatch:
        mpatch.return_value = _make_resp(200, {"id": "abc"})
        tac.rename_tenant("abc", code="C", legal_name="LN")
    assert mpatch.call_args.kwargs["json"] == {"code": "C", "legal_name": "LN"}


def test_rename_tenant_http_error() -> None:
    with patch("ghg_tool.ui.clients.tenant_admin_client.httpx.patch") as mpatch:
        mpatch.return_value = _make_resp(404, {"detail": "not found"})
        result = tac.rename_tenant("abc", code="X")
    assert result["status_code"] == 404


def test_rename_tenant_network_error() -> None:
    with patch("ghg_tool.ui.clients.tenant_admin_client.httpx.patch") as mpatch:
        mpatch.side_effect = httpx.ConnectError("down")
        result = tac.rename_tenant("abc", code="X")
    assert "error" in result


def test_deactivate_tenant_success() -> None:
    with patch("ghg_tool.ui.clients.tenant_admin_client.httpx.delete") as mdel:
        mdel.return_value = _make_resp(200, {"id": "abc", "is_active": False})
        result = tac.deactivate_tenant("abc")
    assert result["is_active"] is False


def test_deactivate_tenant_http_error() -> None:
    with patch("ghg_tool.ui.clients.tenant_admin_client.httpx.delete") as mdel:
        mdel.return_value = _make_resp(403, {"detail": "forbidden"})
        result = tac.deactivate_tenant("abc")
    assert result["status_code"] == 403


def test_deactivate_tenant_network_error() -> None:
    with patch("ghg_tool.ui.clients.tenant_admin_client.httpx.delete") as mdel:
        mdel.side_effect = httpx.ConnectError("x")
        result = tac.deactivate_tenant("abc")
    assert "error" in result


def test_get_auth_headers_with_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the real _get_auth_headers (autouse fixture stubs it elsewhere)."""
    import streamlit as st

    monkeypatch.setattr(
        st, "session_state", {"token": "tok-123"}, raising=False
    )
    # Restore real function for this test only.
    monkeypatch.setattr(
        tac, "_get_auth_headers", tac.__dict__["_get_auth_headers"].__wrapped__
        if hasattr(tac.__dict__["_get_auth_headers"], "__wrapped__")
        else tac._get_auth_headers,
    )
    # Re-import the original function via the module's source to bypass our autouse stub.
    import importlib

    mod = importlib.reload(tac)
    monkeypatch.setattr(
        mod, "_get_base_url", lambda: _BASE
    )
    monkeypatch.setattr(
        "streamlit.session_state", {"token": "tok-123"}, raising=False
    )
    headers = mod._get_auth_headers()
    assert headers["Content-Type"] == "application/json"
    assert headers.get("Authorization", "").startswith("Bearer ")


def test_base_url_default(monkeypatch: pytest.MonkeyPatch) -> None:
    import streamlit as st

    monkeypatch.setattr(st, "session_state", {}, raising=False)
    monkeypatch.setattr(tac, "_DEFAULT_BASE_URL", "http://fallback.example")
    # Replace stub with real impl
    import importlib

    mod = importlib.reload(tac)
    monkeypatch.setattr(mod, "_DEFAULT_BASE_URL", "http://fallback.example")
    monkeypatch.setattr(st, "session_state", {}, raising=False)
    assert mod._get_base_url() == "http://fallback.example"

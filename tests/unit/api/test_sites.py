"""Unit tests for GET /api/v1/sites — M6 schema (site_type + country).

Tests verify:
    1. Response includes ``site_type`` and ``country`` fields (Task A).
    2. All authenticated roles (editor, admin, viewer) can read sites.
    3. Unauthenticated requests are rejected (401).
    4. The response envelope has the expected shape (SitesResponse).
    5. Empty site list is handled gracefully.

The DB session is mocked so tests do not require a live database.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.main import app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_TENANT_ID = str(uuid.uuid4())

_SITE_ROWS: list[dict[str, Any]] = [
    {
        "codice_sito": "FIORANO",
        "full_name": "Stabilimento Fiorano",
        "role": "logistics",
        "geography": "IT",
        "country": "IT",
        "site_type": "MAGAZZINO",
        "eu_ets_installation_id": None,
        "is_active": True,
    },
    {
        "codice_sito": "IANO",
        "full_name": "Stabilimento Iano",
        "role": "production",
        "geography": "IT",
        "country": "IT",
        "site_type": "STABILIMENTO_PRODUTTIVO",
        "eu_ets_installation_id": "IT-ETS-001",
        "is_active": True,
    },
    {
        "codice_sito": "SASSUOLO",
        "full_name": "Ufficio Sassuolo",
        "role": "office",
        "geography": "IT",
        "country": "IT",
        "site_type": "UFFICIO",
        "eu_ets_installation_id": None,
        "is_active": True,
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str) -> CurrentUser:
    return CurrentUser(
        sub=str(uuid.uuid4()),
        role=role,  # type: ignore[arg-type]
        tenant_id=TEST_TENANT_ID,
        jti=str(uuid.uuid4()),
    )


def _make_mock_session(rows: list[dict[str, Any]]) -> Any:
    """Return an async session mock whose execute() yields the given site rows."""

    class _FakeRow:
        """Mimics SQLAlchemy RowMapping for `r._mapping` access."""

        def __init__(self, data: dict[str, Any]) -> None:
            self._mapping = data

    fake_result = MagicMock()
    fake_result.__iter__ = lambda self: iter([_FakeRow(r) for r in rows])

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=fake_result)

    async def _gen() -> AsyncGenerator[Any, None]:
        yield mock_session

    return _gen


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSitesSchemaM6:
    """GET /api/v1/sites returns site_type and country (Task A, M6)."""

    def test_response_includes_site_type_and_country(self) -> None:
        """M6 schema: site_type and country MUST be present in each site entry."""
        app.dependency_overrides[get_current_user] = lambda: _make_user("editor")
        app.dependency_overrides[get_db] = _make_mock_session(_SITE_ROWS)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/sites/")

        app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        data = resp.json()
        sites = data["sites"]
        assert len(sites) == len(_SITE_ROWS)

        for site in sites:
            assert "site_type" in site, f"site_type missing from {site}"
            assert "country" in site, f"country missing from {site}"
            assert site["site_type"] in {
                "STABILIMENTO_PRODUTTIVO",
                "UFFICIO",
                "MAGAZZINO",
            }, f"Unexpected site_type: {site['site_type']}"
            assert len(site["country"]) == 2, f"country must be 2-char ISO: {site['country']}"

    def test_stabilimento_produttivo_site_type_serialized(self) -> None:
        """STABILIMENTO_PRODUTTIVO site_type is serialized correctly for IANO."""
        app.dependency_overrides[get_current_user] = lambda: _make_user("admin")
        app.dependency_overrides[get_db] = _make_mock_session(_SITE_ROWS)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/sites/")

        app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        sites = {s["codice_sito"]: s for s in resp.json()["sites"]}
        assert sites["IANO"]["site_type"] == "STABILIMENTO_PRODUTTIVO"
        assert sites["IANO"]["country"] == "IT"

    def test_magazzino_site_type_serialized(self) -> None:
        """MAGAZZINO site_type is serialized correctly for FIORANO."""
        app.dependency_overrides[get_current_user] = lambda: _make_user("editor")
        app.dependency_overrides[get_db] = _make_mock_session(_SITE_ROWS)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/sites/")

        app.dependency_overrides.clear()

        sites = {s["codice_sito"]: s for s in resp.json()["sites"]}
        assert sites["FIORANO"]["site_type"] == "MAGAZZINO"
        assert sites["FIORANO"]["country"] == "IT"

    def test_ufficio_site_type_serialized(self) -> None:
        """UFFICIO site_type is serialized correctly for SASSUOLO."""
        app.dependency_overrides[get_current_user] = lambda: _make_user("viewer")
        app.dependency_overrides[get_db] = _make_mock_session(_SITE_ROWS)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/sites/")

        app.dependency_overrides.clear()

        sites = {s["codice_sito"]: s for s in resp.json()["sites"]}
        assert sites["SASSUOLO"]["site_type"] == "UFFICIO"
        assert sites["SASSUOLO"]["country"] == "IT"

    def test_response_envelope_has_required_fields(self) -> None:
        """Response envelope includes sites, tenant_id_prefix, correlation_id."""
        app.dependency_overrides[get_current_user] = lambda: _make_user("editor")
        app.dependency_overrides[get_db] = _make_mock_session(_SITE_ROWS)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/sites/")

        app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "sites" in data
        assert "tenant_id_prefix" in data
        assert "correlation_id" in data
        assert len(data["tenant_id_prefix"]) == 8

    def test_empty_site_list_returns_200(self) -> None:
        """When no active sites exist, return HTTP 200 with empty list."""
        app.dependency_overrides[get_current_user] = lambda: _make_user("editor")
        app.dependency_overrides[get_db] = _make_mock_session([])

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/sites/")

        app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["sites"] == []


class TestSitesRBAC:
    """RBAC: all authenticated roles may read sites; unauthenticated must be denied."""

    def test_editor_can_read_sites(self) -> None:
        """editor role has sites.read permission."""
        app.dependency_overrides[get_current_user] = lambda: _make_user("editor")
        app.dependency_overrides[get_db] = _make_mock_session(_SITE_ROWS)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/sites/")

        app.dependency_overrides.clear()
        assert resp.status_code == 200, resp.text

    def test_admin_can_read_sites(self) -> None:
        """admin role has sites.read permission."""
        app.dependency_overrides[get_current_user] = lambda: _make_user("admin")
        app.dependency_overrides[get_db] = _make_mock_session(_SITE_ROWS)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/sites/")

        app.dependency_overrides.clear()
        assert resp.status_code == 200, resp.text

    def test_viewer_can_read_sites(self) -> None:
        """viewer role has sites.read permission."""
        app.dependency_overrides[get_current_user] = lambda: _make_user("viewer")
        app.dependency_overrides[get_db] = _make_mock_session(_SITE_ROWS)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/sites/")

        app.dependency_overrides.clear()
        assert resp.status_code == 200, resp.text

    def test_unauthenticated_returns_401(self) -> None:
        """Requests without Authorization header must return 401."""
        app.dependency_overrides.clear()  # Use real auth (no override)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/sites/")

        assert resp.status_code == 401, resp.text

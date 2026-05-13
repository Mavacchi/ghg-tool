"""Unit tests for /healthz and /readyz endpoints."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from ghg_tool.api.dependencies.db import get_db_no_auth  # noqa: E402
from ghg_tool.api.main import app  # noqa: E402


async def _db_ok():  # type: ignore[return]
    """Mock DB session that passes the SELECT 1 probe."""
    from unittest.mock import AsyncMock
    session = AsyncMock()
    session.execute = AsyncMock()
    yield session


async def _db_fail():  # type: ignore[return]
    """Mock DB session that raises on execute (simulates DB down)."""
    from unittest.mock import AsyncMock
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=RuntimeError("DB unreachable"))
    yield session


def test_healthz_always_200() -> None:
    """GET /healthz returns 200 with status=ok, no auth needed."""
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_ok() -> None:
    """GET /readyz returns 200 when DB is reachable."""
    app.dependency_overrides[get_db_no_auth] = _db_ok
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/readyz")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readyz_503_when_db_down() -> None:
    """GET /readyz returns 503 when DB raises an exception."""
    app.dependency_overrides[get_db_no_auth] = _db_fail
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/readyz")
    app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_openapi_json_accessible() -> None:
    """GET /openapi.json returns a valid 200 response in development mode."""
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "openapi" in data
    assert "paths" in data


def test_swagger_ui_accessible_in_dev() -> None:
    """GET /docs returns HTML in development mode."""
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_delete_emissions_returns_405() -> None:
    """DELETE /api/v1/emissions/{id} must return 405 (not registered)."""
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.delete("/api/v1/emissions/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 405


def test_put_emissions_returns_405() -> None:
    """PUT /api/v1/emissions/{id} must return 405 (not registered)."""
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.put(
            "/api/v1/emissions/00000000-0000-0000-0000-000000000001",
            json={}
        )
    assert response.status_code == 405

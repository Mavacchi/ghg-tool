"""Unit tests for /api/v1/emissions — RBAC, append-only, schema validation."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from fastapi.testclient import TestClient

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT_ID = str(uuid.uuid4())
_FACTOR_ID = str(uuid.uuid4())
_EMISSION_ID = uuid.uuid4()


def _make_user(role: str) -> CurrentUser:
    return CurrentUser(
        sub=str(uuid.uuid4()),
        role=role,  # type: ignore[arg-type]
        tenant_id=_TENANT_ID,
        jti=str(uuid.uuid4()),
    )


def _user_override(role: str) -> Any:
    u = _make_user(role)
    async def _dep() -> CurrentUser:
        return u
    return _dep


def _session_with_emissions(rows: list[Any]) -> Any:
    """Build a mock DB session override that returns given rows from get_active."""
    async def _gen() -> Any:
        session = AsyncMock()
        repo_mock = MagicMock()
        repo_mock.get_active = AsyncMock(return_value=rows)
        yield session
    return _gen


def _empty_session() -> Any:
    async def _gen() -> Any:
        session = AsyncMock()
        yield session
    return _gen


def _emission_orm_row(**kwargs: Any) -> MagicMock:
    """Build a MagicMock that looks like an Emission ORM row."""
    defaults = {
        "id": _EMISSION_ID,
        "tenant_id": uuid.UUID(_TENANT_ID),
        "correlation_id": uuid.uuid4(),
        "raw_row_id": uuid.uuid4(),
        "raw_scope": 1,
        "scope": 1,
        "sub_scope": "combustion",
        "codice_sito": "IANO",
        "anno": 2024,
        "tco2e": 100.0,
        "co2_tonne": 95.0,
        "ch4_tco2e": None,
        "n2o_tco2e": None,
        "co2_biogenic_tonne": None,
        "co2_fossil_tonne": None,
        "factor_id": uuid.UUID(_FACTOR_ID),
        "factor_version": "v1.0",
        "factor_source": "DEFRA",
        "gwp_set": "AR6",
        "methodology": "activity-based",
        "regulatory_stream": "CSRD_ESRS_E1",
        "calc_timestamp": datetime.now(tz=timezone.utc),
        "created_by": "test-user",
        "valid_from": datetime.now(tz=timezone.utc),
        "valid_to": None,
        "superseded_by": None,
        "reason_code": None,
        "disclosure_notes": None,
    }
    defaults.update(kwargs)
    row = MagicMock(spec_set=list(defaults.keys()))
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


# ---------------------------------------------------------------------------
# Tests: RBAC on GET /api/v1/emissions
# ---------------------------------------------------------------------------


class TestEmissionsGet:
    """Tests for GET /api/v1/emissions/."""

    def test_auditor_can_read(self) -> None:
        """auditor role can read emissions."""
        with patch(
            "ghg_tool.api.routers.emissions.EmissionsRepository"
        ) as MockRepo:
            MockRepo.return_value.get_active = AsyncMock(return_value=[])
            app.dependency_overrides[get_current_user] = _user_override("auditor")
            app.dependency_overrides[get_db] = _empty_session()
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/emissions/")
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_esg_manager_can_read(self) -> None:
        """esg_manager role can read emissions."""
        with patch("ghg_tool.api.routers.emissions.EmissionsRepository") as MockRepo:
            MockRepo.return_value.get_active = AsyncMock(return_value=[])
            app.dependency_overrides[get_current_user] = _user_override("esg_manager")
            app.dependency_overrides[get_db] = _empty_session()
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/emissions/")
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_data_steward_can_read(self) -> None:
        """data_steward role can read emissions."""
        with patch("ghg_tool.api.routers.emissions.EmissionsRepository") as MockRepo:
            MockRepo.return_value.get_active = AsyncMock(return_value=[])
            app.dependency_overrides[get_current_user] = _user_override("data_steward")
            app.dependency_overrides[get_db] = _empty_session()
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/emissions/")
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_unauthenticated_returns_401(self) -> None:
        """No token → 401."""
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/emissions/")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: RBAC on POST /api/v1/emissions
# ---------------------------------------------------------------------------

_VALID_CREATE_BODY = {
    "scope": 1,
    "sub_scope": "combustion",
    "codice_sito": "IANO",
    "anno": 2024,
    "tco2e": 50.0,
    "co2_tonne": 48.0,
    "raw_scope": 1,
    "factor_id": str(uuid.uuid4()),
    "factor_version": "v1.0",
    "factor_source": "DEFRA",
    "gwp_set": "AR6",
    "methodology": "activity-based",
    "regulatory_stream": "CSRD_ESRS_E1",
}


class TestEmissionsPost:
    """Tests for POST /api/v1/emissions/."""

    def test_data_steward_can_create(self) -> None:
        """data_steward can POST a new emission row."""
        mock_row = _emission_orm_row()
        with patch("ghg_tool.api.routers.emissions.EmissionsRepository") as MockRepo:
            MockRepo.return_value.insert = AsyncMock(return_value=mock_row)
            app.dependency_overrides[get_current_user] = _user_override("data_steward")
            app.dependency_overrides[get_db] = _empty_session()
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/api/v1/emissions/",
                    json=_VALID_CREATE_BODY,
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                )
            app.dependency_overrides.clear()
        assert resp.status_code == 201
        assert "id" in resp.json()

    def test_auditor_cannot_create(self) -> None:
        """auditor role cannot POST — must return 403."""
        app.dependency_overrides[get_current_user] = _user_override("auditor")
        app.dependency_overrides[get_db] = _empty_session()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/emissions/",
                json=_VALID_CREATE_BODY,
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_esg_manager_cannot_create(self) -> None:
        """esg_manager role cannot POST emissions — must return 403."""
        app.dependency_overrides[get_current_user] = _user_override("esg_manager")
        app.dependency_overrides[get_db] = _empty_session()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/emissions/",
                json=_VALID_CREATE_BODY,
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_missing_idempotency_key_returns_422(self) -> None:
        """POST without Idempotency-Key header returns 422."""
        app.dependency_overrides[get_current_user] = _user_override("data_steward")
        app.dependency_overrides[get_db] = _empty_session()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/emissions/", json=_VALID_CREATE_BODY)
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_negative_tco2e_rejected(self) -> None:
        """POST with negative tco2e must be rejected with 422."""
        bad_body = {**_VALID_CREATE_BODY, "tco2e": -1.0}
        app.dependency_overrides[get_current_user] = _user_override("data_steward")
        app.dependency_overrides[get_db] = _empty_session()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/emissions/",
                json=bad_body,
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_invalid_scope_sub_scope_combo_rejected(self) -> None:
        """scope=1 with sub_scope='LB' (Scope 2 only) must be rejected."""
        bad_body = {**_VALID_CREATE_BODY, "scope": 1, "sub_scope": "LB"}
        app.dependency_overrides[get_current_user] = _user_override("data_steward")
        app.dependency_overrides[get_db] = _empty_session()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/emissions/",
                json=bad_body,
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_invalid_codice_sito_rejected(self) -> None:
        """POST with unknown codice_sito returns 422."""
        bad_body = {**_VALID_CREATE_BODY, "codice_sito": "UNKNOWN_SITE"}
        app.dependency_overrides[get_current_user] = _user_override("data_steward")
        app.dependency_overrides[get_db] = _empty_session()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/emissions/",
                json=bad_body,
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_delete_returns_405(self) -> None:
        """DELETE /api/v1/emissions/{id} must return 405 (append-only, FR-20)."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.delete(f"/api/v1/emissions/{uuid.uuid4()}")
        assert resp.status_code == 405

    def test_put_returns_405(self) -> None:
        """PUT /api/v1/emissions/{id} must return 405 (no PUT route registered)."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.put(f"/api/v1/emissions/{uuid.uuid4()}", json={})
        assert resp.status_code == 405

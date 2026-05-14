"""Unit tests for GET /api/v1/intensity (FR-25, FR-26).

Covers:
  - 200 OK with valid params (mocked DB returning rows)
  - 200 OK stub when DB view is absent (ProgrammingError / OperationalError)
  - 422 for invalid denominator_type (e.g. 'kWh' — not in allowed Literal)
  - 401 when no JWT is provided
  - 403 when caller role lacks intensity:read permission (no role currently
    lacks it per the matrix, so this path is tested by monkeypatching the
    permission matrix to restrict to esg_manager only, then calling as auditor)
  - Query params anno_from / anno_to / codice_sito / gwp_set are forwarded
  - Missing required params (tenant_id / denominator_type) → 422
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# Configure test environment before importing app modules
os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.exc import OperationalError, ProgrammingError  # noqa: E402

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user  # noqa: E402
from ghg_tool.api.dependencies.db import get_db  # noqa: E402
from ghg_tool.api.main import app  # noqa: E402

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_TENANT_ID = str(uuid.uuid4())

# SEC-P0-003: tenant_id is no longer a query parameter (sourced from JWT).
# Tests no longer pass tenant_id in params; the JWT fixture supplies it.
_VALID_PARAMS: dict[str, Any] = {
    "denominator_type": "EUR_revenue",
    "anno_from": 2023,
    "anno_to": 2025,
    "gwp_set": "AR6",
}

# A minimal intensity row dict matching IntensityRow fields
_SAMPLE_ROW: dict[str, Any] = {
    "anno": 2024,
    "codice_sito": None,
    "scope_label": "Scope1",
    "intensity_value": Decimal("0.82"),
    "denominator_value": Decimal("10000000"),
    "denominator_unit": "EUR",
    "gwp_set": "AR6",
    "factor_source": "DEFRA_2025",
    "factor_version": "v1.0",
    "methodology": "activity-based",
    "hr_confirmation_date": None,
    "confidence_interval_lower": None,
    "confidence_interval_upper": None,
    "correlation_id": str(uuid.uuid4()),
}


def _make_user(role: str) -> CurrentUser:
    return CurrentUser(
        sub=str(uuid.uuid4()),
        role=role,  # type: ignore[arg-type]
        tenant_id=_TENANT_ID,
        jti=str(uuid.uuid4()),
    )


def _auth_override(role: str) -> Any:
    user = _make_user(role)

    async def _dep() -> CurrentUser:
        return user

    return _dep


def _mock_db_with_rows(rows: list[dict[str, Any]]) -> Any:
    """Return a DB override that yields rows from session.execute()."""

    async def _gen() -> AsyncGenerator[Any, None]:
        session = AsyncMock()
        # Build mock result rows using MagicMock with _mapping attribute
        mock_result_rows = []
        for row in rows:
            mock_row = MagicMock()
            mock_row._mapping = row
            mock_result_rows.append(mock_row)
        mock_result = MagicMock()
        # Make iteration over result work
        mock_result.__iter__ = MagicMock(return_value=iter(mock_result_rows))
        session.execute = AsyncMock(return_value=mock_result)
        yield session

    return _gen


def _mock_db_empty() -> Any:
    """Return a DB override that yields no rows."""
    return _mock_db_with_rows([])


def _mock_db_error(exc_class: type[Exception]) -> Any:
    """Return a DB override that raises the given SQLAlchemy exception."""

    async def _gen() -> AsyncGenerator[Any, None]:
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=exc_class("view not found", None, None))
        yield session

    return _gen


def _teardown() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestGetIntensity:
    """Tests for GET /api/v1/intensity/."""

    def test_200_ok_with_valid_params_and_mocked_rows(self) -> None:
        """200 OK returned when DB yields intensity rows; response shape correct."""
        app.dependency_overrides[get_current_user] = _auth_override("data_steward")
        app.dependency_overrides[get_db] = _mock_db_with_rows([_SAMPLE_ROW])

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/intensity/", params=_VALID_PARAMS)

        _teardown()

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "rows" in data
        assert data["denominator_type"] == "EUR_revenue"
        assert data["gwp_set"] == "AR6"
        assert data["anno_from"] == 2023
        assert data["anno_to"] == 2025
        assert "correlation_id" in data
        assert "as_of" in data
        assert len(data["rows"]) == 1
        row = data["rows"][0]
        assert row["anno"] == 2024
        assert row["scope_label"] == "Scope1"
        assert row["gwp_set"] == "AR6"
        assert row["factor_source"] == "DEFRA_2025"

    def test_200_ok_stub_when_mv_absent_programming_error(self) -> None:
        """ProgrammingError (MV not yet created) → 200 with empty rows and note."""
        app.dependency_overrides[get_current_user] = _auth_override("auditor")
        app.dependency_overrides[get_db] = _mock_db_error(ProgrammingError)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/intensity/", params=_VALID_PARAMS)

        _teardown()

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["rows"] == []
        # Note is present under "_note" key (alias)
        assert "_note" in data or "note" in data

    def test_200_ok_stub_when_mv_absent_operational_error(self) -> None:
        """OperationalError (DB down / table missing) → 200 stub response."""
        app.dependency_overrides[get_current_user] = _auth_override("esg_manager")
        app.dependency_overrides[get_db] = _mock_db_error(OperationalError)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/intensity/", params=_VALID_PARAMS)

        _teardown()

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["rows"] == []

    def test_422_invalid_denominator_type(self) -> None:
        """denominator_type='kWh' is not in the allowed Literal → 422."""
        app.dependency_overrides[get_current_user] = _auth_override("data_steward")
        app.dependency_overrides[get_db] = _mock_db_empty()

        bad_params = {**_VALID_PARAMS, "denominator_type": "kWh"}
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/intensity/", params=bad_params)

        _teardown()

        assert resp.status_code == 422, resp.text

    def test_422_invalid_gwp_set(self) -> None:
        """gwp_set='AR4' is not in the allowed Literal → 422 from FastAPI validation."""
        app.dependency_overrides[get_current_user] = _auth_override("data_steward")
        app.dependency_overrides[get_db] = _mock_db_empty()

        bad_params = {**_VALID_PARAMS, "gwp_set": "AR4"}
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/intensity/", params=bad_params)

        _teardown()

        # FastAPI validates the Literal at query-param parse time → 422
        assert resp.status_code == 422, resp.text

    def test_401_no_jwt(self) -> None:
        """No Authorization header → 401."""
        # Clear all overrides so the real JWT decode runs
        app.dependency_overrides.clear()

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/intensity/", params=_VALID_PARAMS)

        _teardown()

        assert resp.status_code == 401, resp.text

    def test_403_role_too_low_when_matrix_restricted(self) -> None:
        """When permission matrix restricts intensity:read to esg_manager only,
        an auditor caller receives 403.

        This test patches the RBAC matrix to simulate a stricter policy, verifying
        that the require_permission dependency correctly enforces the matrix.
        """
        app.dependency_overrides[get_current_user] = _auth_override("auditor")
        app.dependency_overrides[get_db] = _mock_db_empty()

        with (
            patch(
                "ghg_tool.infrastructure.security.rbac.PERMISSION_MATRIX",
                {
                    "intensity": {
                        "read": frozenset({"esg_manager"}),  # auditor excluded
                    },
                },
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get("/api/v1/intensity/", params=_VALID_PARAMS)

        _teardown()

        assert resp.status_code == 403, resp.text

    def test_tenant_id_sourced_from_jwt_not_query_string(self) -> None:
        """SEC-P0-003: tenant_id is sourced from JWT, not the query string.

        The endpoint no longer accepts tenant_id as a query parameter; it is
        silently ignored if passed (or treated as an unknown param, yielding 200).
        Omitting tenant_id from params should return 200 (no 422) because the
        tenant is taken from the JWT user fixture (_TENANT_ID).
        """
        app.dependency_overrides[get_current_user] = _auth_override("data_steward")
        app.dependency_overrides[get_db] = _mock_db_empty()

        params_no_tenant = {
            k: v for k, v in _VALID_PARAMS.items() if k != "tenant_id"
        }
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/intensity/", params=params_no_tenant)

        _teardown()

        # tenant_id is no longer a query param — request succeeds with JWT tenant
        assert resp.status_code == 200, resp.text

    def test_422_missing_denominator_type(self) -> None:
        """Missing required denominator_type → 422."""
        app.dependency_overrides[get_current_user] = _auth_override("data_steward")
        app.dependency_overrides[get_db] = _mock_db_empty()

        params_no_denom = {
            k: v for k, v in _VALID_PARAMS.items() if k != "denominator_type"
        }
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/intensity/", params=params_no_denom)

        _teardown()

        assert resp.status_code == 422, resp.text

    def test_all_roles_can_read_by_default(self) -> None:
        """All three roles (data_steward, esg_manager, auditor) receive 200."""
        for role in ("data_steward", "esg_manager", "auditor"):
            app.dependency_overrides[get_current_user] = _auth_override(role)
            app.dependency_overrides[get_db] = _mock_db_empty()

            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/intensity/", params=_VALID_PARAMS)

            _teardown()
            assert resp.status_code == 200, f"Expected 200 for role={role}; got {resp.status_code}"

    def test_codice_sito_filter_accepted(self) -> None:
        """codice_sito query param is accepted and does not cause errors."""
        app.dependency_overrides[get_current_user] = _auth_override("data_steward")
        app.dependency_overrides[get_db] = _mock_db_empty()

        params_with_site = {**_VALID_PARAMS, "codice_sito": "IANO"}
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/intensity/", params=params_with_site)

        _teardown()
        assert resp.status_code == 200, resp.text

    def test_fte_denominator_accepted(self) -> None:
        """FTE denominator type is accepted (REV-017 hr_confirmation_date traceability)."""
        fte_row = {**_SAMPLE_ROW, "denominator_unit": "FTE", "hr_confirmation_date": "2024-03-01"}
        app.dependency_overrides[get_current_user] = _auth_override("esg_manager")
        app.dependency_overrides[get_db] = _mock_db_with_rows([fte_row])

        params_fte = {**_VALID_PARAMS, "denominator_type": "FTE"}
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/intensity/", params=params_fte)

        _teardown()
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["denominator_type"] == "FTE"
        assert data["rows"][0]["hr_confirmation_date"] == "2024-03-01"

    def test_no_delete_endpoint_on_intensity(self) -> None:
        """DELETE /api/v1/intensity/ is not registered → 405 or 404 (append-only)."""
        app.dependency_overrides[get_current_user] = _auth_override("esg_manager")
        app.dependency_overrides[get_db] = _mock_db_empty()

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.delete("/api/v1/intensity/")

        _teardown()
        assert resp.status_code in (404, 405), resp.text

    def test_response_envelope_fields_present(self) -> None:
        """IntensityResponse envelope must include all mandatory fields."""
        app.dependency_overrides[get_current_user] = _auth_override("auditor")
        app.dependency_overrides[get_db] = _mock_db_empty()

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/intensity/", params=_VALID_PARAMS)

        _teardown()

        assert resp.status_code == 200
        data = resp.json()
        for field in ("rows", "denominator_type", "gwp_set", "anno_from", "anno_to",
                      "correlation_id", "as_of"):
            assert field in data, f"Missing field: {field}"

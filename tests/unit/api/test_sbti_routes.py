"""Unit tests for /api/v1/sbti endpoints.

All DB access is mocked via app.dependency_overrides + unittest.mock.
No live PostgreSQL instance is required.

Covers (10 cases):
  1. list_targets 200 -- active targets returned
  2. list_targets with include_inactive=true as viewer -> 403
  3. create_target happy path -> 201
  4. create_target 422 invalid scope_coverage
  5. create_target 422 target_year <= baseline_year
  6. deactivate_target happy path -> 200
  7. deactivate_target 404 wrong tenant (row not found)
  8. get_trajectory happy path with actuals -> 200
  9. 401 unauthenticated on list endpoint
  10. 403 editor on create (write-protected)
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from fastapi.testclient import TestClient

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.main import app
from ghg_tool.infrastructure.db.models.sbti_target import SbtiTarget

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TENANT = str(uuid.uuid4())
_ESG_USER = str(uuid.uuid4())
_DS_USER = str(uuid.uuid4())
_VIEWER_USER = str(uuid.uuid4())
_TARGET_UUID = uuid.uuid4()

_LIST_URL = "/api/v1/sbti/targets"
_CREATE_URL = "/api/v1/sbti/targets"
_DEACTIVATE_URL = f"/api/v1/sbti/targets/{_TARGET_UUID}/deactivate"
_TRAJECTORY_URL = f"/api/v1/sbti/targets/{_TARGET_UUID}/trajectory"

_VALID_BODY: dict[str, Any] = {
    "name": "Near-term S1+S2 -42%",
    "scope_coverage": "S1+S2_MB",
    "baseline_year": 2021,
    "baseline_tco2e": "10000.000",
    "target_year": 2030,
    "target_tco2e": "5800.000",
    "alignment": "1.5C",
    "methodology": "SBTi_ACA",
    "sbti_approval_status": "committed",
    "sbti_validation_date": None,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str, user_id: str) -> CurrentUser:
    return CurrentUser(
        sub=user_id,
        role=role,  # type: ignore[arg-type]
        tenant_id=_TENANT,
        jti=str(uuid.uuid4()),
    )


def _auth(role: str, user_id: str) -> Any:
    user = _make_user(role, user_id)

    async def _dep() -> CurrentUser:
        return user

    return _dep


def _noop_db() -> Any:
    async def _override() -> AsyncGenerator[Any, None]:
        yield MagicMock()

    return _override


def _make_target_orm(
    *,
    target_id: uuid.UUID = _TARGET_UUID,
    is_active: bool = True,
) -> SbtiTarget:
    row = MagicMock(spec=SbtiTarget)
    row.target_id = target_id
    row.tenant_id = uuid.UUID(_TENANT)
    row.name = "Near-term S1+S2 -42%"
    row.scope_coverage = "S1+S2_MB"
    row.baseline_year = 2021
    row.baseline_tco2e = Decimal("10000.000")
    row.target_year = 2030
    row.target_tco2e = Decimal("5800.000")
    row.reduction_pct = Decimal("42.0000")
    row.alignment = "1.5C"
    row.methodology = "SBTi_ACA"
    row.sbti_approval_status = "committed"
    row.sbti_validation_date = None
    row.created_by = _ESG_USER
    row.created_at = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    row.is_active = is_active
    return row


# ---------------------------------------------------------------------------
# Test 1: list_targets returns 200 with active targets
# ---------------------------------------------------------------------------


def test_list_targets_200() -> None:
    """Active targets are returned to any authenticated role."""
    target = _make_target_orm()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [target]
    mock_session.execute.return_value = mock_result

    async def _db() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[get_current_user] = _auth("viewer", _VIEWER_USER)
    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(_LIST_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["scope_coverage"] == "S1+S2_MB"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 2: include_inactive=true as viewer -> 403
# ---------------------------------------------------------------------------


def test_list_targets_include_inactive_auditor_403() -> None:
    """Non-admin cannot request include_inactive=true."""
    app.dependency_overrides[get_current_user] = _auth("viewer", _VIEWER_USER)
    app.dependency_overrides[get_db] = _noop_db()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(_LIST_URL, params={"include_inactive": "true"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 3: create_target happy path -> 201
# ---------------------------------------------------------------------------


def test_create_target_201() -> None:
    """admin can create a valid target; response is 201."""
    created_row = _make_target_orm()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    # No existing active target for this scope.
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()

    # After refresh, row reflects the created state.
    async def _refresh(obj: Any) -> None:
        obj.target_id = created_row.target_id
        obj.tenant_id = created_row.tenant_id
        obj.name = created_row.name
        obj.scope_coverage = created_row.scope_coverage
        obj.baseline_year = created_row.baseline_year
        obj.baseline_tco2e = created_row.baseline_tco2e
        obj.target_year = created_row.target_year
        obj.target_tco2e = created_row.target_tco2e
        obj.reduction_pct = created_row.reduction_pct
        obj.alignment = created_row.alignment
        obj.methodology = created_row.methodology
        obj.sbti_approval_status = created_row.sbti_approval_status
        obj.sbti_validation_date = created_row.sbti_validation_date
        obj.created_by = created_row.created_by
        obj.created_at = created_row.created_at
        obj.is_active = True

    mock_session.refresh = _refresh

    async def _db() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[get_current_user] = _auth("admin", _ESG_USER)
    app.dependency_overrides[get_db] = _db
    try:
        with (
            patch("ghg_tool.api.routers.sbti.siem.emit"),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(_CREATE_URL, json=_VALID_BODY)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["scope_coverage"] == "S1+S2_MB"
        assert data["is_active"] is True
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 4: create_target 422 invalid scope_coverage
# ---------------------------------------------------------------------------


def test_create_target_422_invalid_scope() -> None:
    """Invalid scope_coverage fails Pydantic model_validator -> 422."""
    bad_body = {**_VALID_BODY, "scope_coverage": "INVALID_SCOPE"}
    app.dependency_overrides[get_current_user] = _auth("admin", _ESG_USER)
    app.dependency_overrides[get_db] = _noop_db()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_CREATE_URL, json=bad_body)
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 5: create_target 422 target_year <= baseline_year
# ---------------------------------------------------------------------------


def test_create_target_422_year_order() -> None:
    """target_year == baseline_year fails model_validator -> 422."""
    bad_body = {**_VALID_BODY, "target_year": 2021}  # == baseline_year
    app.dependency_overrides[get_current_user] = _auth("admin", _ESG_USER)
    app.dependency_overrides[get_db] = _noop_db()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_CREATE_URL, json=bad_body)
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 6: deactivate_target happy path -> 200
# ---------------------------------------------------------------------------


def test_deactivate_target_200() -> None:
    """admin can deactivate an active target."""
    active_row = _make_target_orm(is_active=True)
    _make_target_orm(is_active=False)

    mock_session = AsyncMock()
    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = active_row
    update_result = MagicMock()
    update_result.rowcount = 1

    call_count = 0

    async def _execute(stmt: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return fetch_result
        return update_result

    mock_session.execute = _execute
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    async def _refresh(obj: Any) -> None:
        obj.is_active = False

    mock_session.refresh = _refresh

    async def _db() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[get_current_user] = _auth("admin", _ESG_USER)
    app.dependency_overrides[get_db] = _db
    try:
        with (
            patch("ghg_tool.api.routers.sbti.siem.emit"),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.patch(_DEACTIVATE_URL)
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_active"] is False
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 7: deactivate_target 404 wrong tenant
# ---------------------------------------------------------------------------


def test_deactivate_target_404_wrong_tenant() -> None:
    """Target belonging to a different tenant returns 404."""
    mock_session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None  # Not found in this tenant.
    mock_session.execute.return_value = result

    async def _db() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[get_current_user] = _auth("admin", _ESG_USER)
    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(_DEACTIVATE_URL)
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 8: get_trajectory happy path with actuals -> 200
# ---------------------------------------------------------------------------


def test_get_trajectory_200_with_actuals() -> None:
    """Trajectory endpoint returns points with actuals and a status."""
    target_row = _make_target_orm()

    mock_session = AsyncMock()
    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = target_row

    actual_row = MagicMock()
    actual_row.anno = 2022
    actual_row.total = Decimal("9200.000")
    actuals_result = MagicMock()
    actuals_result.__iter__ = MagicMock(return_value=iter([actual_row]))

    call_count = 0

    async def _execute(stmt: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return target_result
        return actuals_result

    mock_session.execute = _execute

    async def _db() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[get_current_user] = _auth("viewer", _VIEWER_USER)
    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(_TRAJECTORY_URL)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "trajectory" in data
        assert "status" in data
        assert len(data["trajectory"]) > 0
        # Baseline year (2021) and target year (2030) must be present.
        years = [p["year"] for p in data["trajectory"]]
        assert 2021 in years
        assert 2030 in years
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 9: 401 unauthenticated
# ---------------------------------------------------------------------------


def test_list_targets_401_unauthenticated() -> None:
    """Missing JWT returns 401."""
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get(_LIST_URL)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test 10: 403 editor on write
# ---------------------------------------------------------------------------


def test_create_target_403_data_steward() -> None:
    """editor cannot create SBTi targets (admin only)."""
    app.dependency_overrides[get_current_user] = _auth("editor", _DS_USER)
    app.dependency_overrides[get_db] = _noop_db()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_CREATE_URL, json=_VALID_BODY)
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()

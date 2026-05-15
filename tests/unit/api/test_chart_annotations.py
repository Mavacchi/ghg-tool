"""Unit tests for /api/v1/chart-annotations endpoints.

All DB access is mocked via ``app.dependency_overrides`` + ``unittest.mock``.
No live PostgreSQL instance is required.

include_hidden policy under test (documented decision):
  Only ``esg_manager`` and ``auditor`` may request ``include_hidden=true``.
  ``data_steward`` always receives only visible annotations regardless of
  the flag value. This matches the module-level docstring of chart_annotations.py.
  Rationale: data_steward is an operational ingestion role; auditors and
  esg_managers need to inspect hidden entries for ISAE 3000 reviews.

Test cases:
  1.  POST happy path (data_steward) returns 201 with id.
  2.  POST as auditor returns 403.
  3.  GET filtered by chart_key returns only matching rows (mocked).
  4.  GET as auditor with include_hidden=true returns 200 (allowed).
  5.  GET as data_steward with include_hidden=true returns 403 (not allowed).
  6.  PATCH visibility flips is_visible; second flip returns the toggled value.
  7.  PATCH acknowledge sets timestamp; second call returns 409.
  8.  PATCH visibility when DB trigger fires returns 409 with error_code
      chart_annotation_immutable.
  9.  POST with invalid severity returns 422.
  10. GET missing chart_key returns 422 (required query param).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from fastapi.testclient import TestClient

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.main import app
from ghg_tool.infrastructure.db.models.chart_annotation import ChartAnnotation

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TENANT = str(uuid.uuid4())
_DS_USER = str(uuid.uuid4())
_ESG_USER = str(uuid.uuid4())
_AUDITOR_USER = str(uuid.uuid4())
_ANN_UUID = uuid.uuid4()

_BASE_URL = "/api/v1/chart-annotations"

_VALID_POST_BODY: dict[str, Any] = {
    "chart_key": "drilldown_scope",
    "anchor_year": 2024,
    "anchor_label": "Q3 kiln outage",
    "title": "Calo emissioni Q3",
    "body": "Il forno VIANO era fermo per manutenzione straordinaria luglio-settembre.",
    "severity": "INFO",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str, user_id: str) -> CurrentUser:
    """Build a CurrentUser for dependency override.

    Args:
        role: RBAC role code.
        user_id: User UUID string.

    Returns:
        Populated CurrentUser.
    """
    return CurrentUser(
        sub=user_id,
        role=role,  # type: ignore[arg-type]
        tenant_id=_TENANT,
        jti=str(uuid.uuid4()),
    )


def _auth(role: str, user_id: str) -> Any:
    """Return an async dependency override for get_current_user.

    Args:
        role: The role to inject.
        user_id: The user UUID string.

    Returns:
        An async callable returning a CurrentUser.
    """
    user = _make_user(role, user_id)

    async def _dep() -> CurrentUser:
        return user

    return _dep


def _noop_db() -> Any:
    """Return a no-op async DB session override.

    Returns:
        An async generator yielding a MagicMock session.
    """
    async def _override() -> AsyncGenerator[Any, None]:
        yield MagicMock()

    return _override


def _make_annotation_orm(
    *,
    annotation_id: uuid.UUID = _ANN_UUID,
    chart_key: str = "drilldown_scope",
    anchor_year: int | None = 2024,
    is_visible: bool = True,
    acknowledged_by: str | None = None,
    acknowledged_at: datetime | None = None,
) -> ChartAnnotation:
    """Build a mock ChartAnnotation ORM row.

    Args:
        annotation_id: UUID for the row's primary key.
        chart_key: Logical chart identifier.
        anchor_year: Year the annotation is anchored to.
        is_visible: Visibility flag.
        acknowledged_by: User sub who acknowledged, or None.
        acknowledged_at: Acknowledgement timestamp, or None.

    Returns:
        A MagicMock spec'd to ChartAnnotation.
    """
    row = MagicMock(spec=ChartAnnotation)
    row.id = annotation_id
    row.tenant_id = uuid.UUID(_TENANT)
    row.chart_key = chart_key
    row.anchor_year = anchor_year
    row.anchor_label = "Q3 kiln outage"
    row.title = "Calo emissioni Q3"
    row.body = "Il forno VIANO era fermo."
    row.severity = "INFO"
    row.created_at = datetime(2024, 10, 1, 12, 0, 0, tzinfo=UTC)
    row.created_by = _DS_USER
    row.is_visible = is_visible
    row.acknowledged_by = acknowledged_by
    row.acknowledged_at = acknowledged_at
    row.extra = None
    return row


# ---------------------------------------------------------------------------
# Test 1: POST happy path returns 201 with id (data_steward)
# ---------------------------------------------------------------------------


def test_post_annotation_201_data_steward() -> None:
    """data_steward can create an annotation; response is 201 with an id field."""
    created_row = _make_annotation_orm()

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    async def _refresh(obj: Any) -> None:
        obj.id = created_row.id
        obj.tenant_id = created_row.tenant_id
        obj.chart_key = created_row.chart_key
        obj.anchor_year = created_row.anchor_year
        obj.anchor_label = created_row.anchor_label
        obj.title = created_row.title
        obj.body = created_row.body
        obj.severity = created_row.severity
        obj.created_at = created_row.created_at
        obj.created_by = created_row.created_by
        obj.is_visible = True
        obj.acknowledged_by = None
        obj.acknowledged_at = None
        obj.extra = None

    mock_session.refresh = _refresh

    async def _db() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[get_current_user] = _auth("data_steward", _DS_USER)
    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_BASE_URL + "/", json=_VALID_POST_BODY)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "id" in data
        assert data["chart_key"] == "drilldown_scope"
        assert data["severity"] == "INFO"
        assert data["is_visible"] is True
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 2: POST as auditor returns 403
# ---------------------------------------------------------------------------


def test_post_annotation_403_auditor() -> None:
    """Auditor lacks write permission; POST returns 403."""
    app.dependency_overrides[get_current_user] = _auth("auditor", _AUDITOR_USER)
    app.dependency_overrides[get_db] = _noop_db()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_BASE_URL + "/", json=_VALID_POST_BODY)
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 3: GET filtered by chart_key returns only matching rows
# ---------------------------------------------------------------------------


def test_get_annotations_filtered_by_chart_key() -> None:
    """GET returns only rows matching the requested chart_key."""
    matching = _make_annotation_orm(chart_key="drilldown_scope")
    _make_annotation_orm(
        annotation_id=uuid.uuid4(), chart_key="trend_scope_total"
    )
    # The query should filter server-side; simulate by returning only matching.
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [matching]
    mock_session.execute.return_value = mock_result

    async def _db() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[get_current_user] = _auth("auditor", _AUDITOR_USER)
    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                _BASE_URL + "/", params={"chart_key": "drilldown_scope"}
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["chart_key"] == "drilldown_scope"
        # Ensure the other chart_key row is not present.
        for row in data:
            assert row["chart_key"] != "trend_scope_total"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 4: GET as auditor with include_hidden=true returns 200
# ---------------------------------------------------------------------------


def test_get_annotations_auditor_include_hidden_200() -> None:
    """Auditors may request include_hidden=true and receive a 200 response."""
    hidden_row = _make_annotation_orm(is_visible=False)

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [hidden_row]
    mock_session.execute.return_value = mock_result

    async def _db() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[get_current_user] = _auth("auditor", _AUDITOR_USER)
    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                _BASE_URL + "/",
                params={"chart_key": "drilldown_scope", "include_hidden": "true"},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list)
        # The mocked session returned the hidden row; it should appear.
        assert len(data) == 1
        assert data[0]["is_visible"] is False
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 5: GET as data_steward with include_hidden=true returns 403
# ---------------------------------------------------------------------------


def test_get_annotations_data_steward_include_hidden_403() -> None:
    """data_steward requesting include_hidden=true is rejected with 403.

    Policy: only esg_manager and auditor may see hidden annotations.
    """
    app.dependency_overrides[get_current_user] = _auth("data_steward", _DS_USER)
    app.dependency_overrides[get_db] = _noop_db()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                _BASE_URL + "/",
                params={"chart_key": "drilldown_scope", "include_hidden": "true"},
            )
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["error_code"] == "insufficient_role_for_hidden"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 6: PATCH visibility flips is_visible; second flip flips back
# ---------------------------------------------------------------------------


def test_patch_visibility_flip_and_reflip() -> None:
    """PATCH visibility toggles is_visible; a second PATCH toggles it back."""
    row = _make_annotation_orm(is_visible=True)

    def _make_session_for_visibility(target_visible: bool) -> AsyncMock:
        """Build a mock session that simulates the visibility flip.

        Args:
            target_visible: The expected new is_visible value.

        Returns:
            Configured mock session.
        """
        mock_session = AsyncMock()
        fetch_result = MagicMock()
        # Simulate fetching existing row.
        fetch_result.scalar_one_or_none.return_value = row
        mock_session.execute.return_value = fetch_result
        mock_session.flush = AsyncMock()

        async def _refresh(obj: Any) -> None:
            obj.is_visible = target_visible

        mock_session.refresh = _refresh
        return mock_session

    # First flip: True -> False
    session1 = _make_session_for_visibility(False)

    async def _db1() -> AsyncGenerator[Any, None]:
        yield session1

    app.dependency_overrides[get_current_user] = _auth("data_steward", _DS_USER)
    app.dependency_overrides[get_db] = _db1
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp1 = client.patch(
                f"{_BASE_URL}/{_ANN_UUID}/visibility",
                json={"is_visible": False},
            )
        assert resp1.status_code == 200, resp1.text
        assert resp1.json()["is_visible"] is False
    finally:
        app.dependency_overrides.clear()

    # Second flip: False -> True
    row.is_visible = False
    session2 = _make_session_for_visibility(True)

    async def _db2() -> AsyncGenerator[Any, None]:
        yield session2

    app.dependency_overrides[get_current_user] = _auth("data_steward", _DS_USER)
    app.dependency_overrides[get_db] = _db2
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp2 = client.patch(
                f"{_BASE_URL}/{_ANN_UUID}/visibility",
                json={"is_visible": True},
            )
        assert resp2.status_code == 200, resp2.text
        assert resp2.json()["is_visible"] is True
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 7: PATCH acknowledge sets timestamp; second call returns 409
# ---------------------------------------------------------------------------


def test_patch_acknowledge_sets_timestamp_and_409_on_second() -> None:
    """First acknowledge sets acknowledged_by/at; second call returns 409."""
    row = _make_annotation_orm(acknowledged_by=None, acknowledged_at=None)

    mock_session = AsyncMock()
    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = row
    mock_session.execute.return_value = fetch_result
    mock_session.flush = AsyncMock()
    _ack_time = datetime(2024, 10, 15, 9, 0, 0, tzinfo=UTC)

    async def _refresh(obj: Any) -> None:
        obj.acknowledged_by = _ESG_USER
        obj.acknowledged_at = _ack_time

    mock_session.refresh = _refresh

    async def _db() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[get_current_user] = _auth("esg_manager", _ESG_USER)
    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(f"{_BASE_URL}/{_ANN_UUID}/acknowledge")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["acknowledged_by"] == _ESG_USER
        assert data["acknowledged_at"] is not None
    finally:
        app.dependency_overrides.clear()

    # Second call: acknowledged_by is now set -> 409
    row.acknowledged_by = _ESG_USER
    row.acknowledged_at = _ack_time

    app.dependency_overrides[get_current_user] = _auth("esg_manager", _ESG_USER)
    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp2 = client.patch(f"{_BASE_URL}/{_ANN_UUID}/acknowledge")
        assert resp2.status_code == 409, resp2.text
        detail = resp2.json()["detail"]
        assert detail["error_code"] == "chart_annotation_already_acknowledged"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 8: DB trigger error on PATCH visibility maps to 409 chart_annotation_immutable
# ---------------------------------------------------------------------------


def test_patch_visibility_db_trigger_raises_409() -> None:
    """If the DB trigger fires during flush, the router returns 409 with
    error_code 'chart_annotation_immutable'.

    We simulate this by raising an exception whose type name contains
    'RaiseException' (asyncpg naming) during session.flush().
    """
    row = _make_annotation_orm(is_visible=True)

    # Create a mock exception whose type name contains 'RaiseException'.
    class RaiseException(Exception):  # noqa: N818
        pass

    mock_session = AsyncMock()
    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = row
    mock_session.execute.return_value = fetch_result
    mock_session.flush = AsyncMock(side_effect=RaiseException("immutable column"))

    async def _db() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[get_current_user] = _auth("data_steward", _DS_USER)
    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(
                f"{_BASE_URL}/{_ANN_UUID}/visibility",
                json={"is_visible": False},
            )
        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert detail["error_code"] == "chart_annotation_immutable"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 9: POST with invalid severity returns 422
# ---------------------------------------------------------------------------


def test_post_invalid_severity_422() -> None:
    """Severity value not in {INFO, WARNING, CRITICAL} fails validation -> 422."""
    bad_body = {**_VALID_POST_BODY, "severity": "DEBUG"}
    app.dependency_overrides[get_current_user] = _auth("data_steward", _DS_USER)
    app.dependency_overrides[get_db] = _noop_db()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_BASE_URL + "/", json=bad_body)
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 10: GET without chart_key returns 422 (required query parameter)
# ---------------------------------------------------------------------------


def test_get_annotations_missing_chart_key_422() -> None:
    """chart_key is a required query parameter; omitting it returns 422."""
    app.dependency_overrides[get_current_user] = _auth("auditor", _AUDITOR_USER)
    app.dependency_overrides[get_db] = _noop_db()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(_BASE_URL + "/")  # no chart_key param
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()

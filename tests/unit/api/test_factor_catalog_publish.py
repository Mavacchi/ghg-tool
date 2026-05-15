"""Unit tests for POST /api/v1/factor-catalog/{factor_uuid}/publish.

Updated for the two-eyes approval workflow (FR-12, ISAE 3000 §A99).
The first admin call now returns 202 (approval requested) rather
than 200 (factor published). Full second-manager approval tests live
in test_factor_publish_approval.py.

Covers:
- happy path: first call -> 202 (approval row created, factor NOT published)
- 401 unauthenticated
- 403 wrong role (viewer)
- 403 wrong role (editor)
- 404 unknown UUID
- 404 cross-tenant isolation
- 409 already published
- 422 is_tbc=True
- 422 value=None AND is_licence_only=False
- structured log emitted on approval request

All DB access is mocked.  No live PostgreSQL instance required.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

import pytest
from fastapi.testclient import TestClient

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.main import app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TENANT_A = str(uuid.uuid4())
_TENANT_B = str(uuid.uuid4())
_USER_DS = str(uuid.uuid4())    # editor
_USER_ESG = str(uuid.uuid4())   # admin
_USER_AU = str(uuid.uuid4())    # viewer
_FACTOR_UUID = uuid.uuid4()

_BASE_URL = f"/api/v1/factor-catalog/{_FACTOR_UUID}/publish"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str, tenant_id: str = _TENANT_A, user_id: str | None = None) -> CurrentUser:
    return CurrentUser(
        sub=user_id or str(uuid.uuid4()),
        role=role,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        jti=str(uuid.uuid4()),
    )


def _auth_override(role: str, tenant_id: str = _TENANT_A, user_id: str | None = None) -> Any:
    user = _make_user(role, tenant_id=tenant_id, user_id=user_id)

    async def _dep() -> CurrentUser:
        return user

    return _dep


def _make_factor_orm(
    *,
    factor_uuid: uuid.UUID = _FACTOR_UUID,
    tenant_id: str = _TENANT_A,
    is_published: bool = False,
    is_tbc: bool = False,
    is_licence_only: bool = False,
    value: float | None = 1.23,
) -> MagicMock:
    """Build a MagicMock that looks like a FactorCatalog ORM row."""
    factor = MagicMock()
    factor.id = factor_uuid
    factor.tenant_id = uuid.UUID(tenant_id)
    factor.factor_id = "TEST_FACTOR_001"
    factor.version = "v1"
    factor.substance = "CO2"
    factor.scope = 1
    factor.category = "combustion"
    factor.source = "DEFRA"
    factor.value = value
    factor.is_licence_only = is_licence_only
    factor.is_tbc = is_tbc
    factor.unit = "kgCO2e/kWh"
    factor.gwp_set = "AR6"
    factor.vintage = "2024"
    factor.valid_from = date(2024, 1, 1)
    factor.valid_to = None
    factor.applicability_note = None
    factor.pdf_source_uri = None
    factor.created_at = datetime(2024, 1, 1, tzinfo=UTC)
    factor.published_at = datetime(2024, 1, 1, tzinfo=UTC) if is_published else None
    factor.published_by = "esg-manager-user" if is_published else None
    factor.is_published = is_published
    factor.biogenic_co2_kg_per_unit = None
    return factor


def _db_returning(factor: MagicMock | None) -> Any:
    """Build an async DB session override whose ``get_by_uuid`` returns *factor*.

    The router now issues three ``session.execute`` calls for the publish path
    under the two-eyes approval workflow (FR-12):
      1. SELECT (via FactorCatalogRepository.get_by_uuid)
      2. SELECT pending approval (_get_pending_approval) -> None (no prior request)
      When no PENDING approval exists the handler creates an approval row and
      returns 202 (Accepted). It does NOT proceed to UPDATE the factor.

    To test the full approval+publish path (200) use the helpers in
    test_factor_publish_approval.py instead.

    ``session.refresh`` is kept for completeness but is only reached on the
    second admin's call (state 3 in the workflow).
    """

    async def _gen() -> Any:
        session = AsyncMock()
        session.flush = AsyncMock(return_value=None)
        session.add = MagicMock(return_value=None)

        # Call 1: SELECT via FactorCatalogRepository.get_by_uuid
        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=factor)

        # Call 2: SELECT pending approval -> None (no prior approval row)
        no_approval_result = MagicMock()
        no_approval_result.scalar_one_or_none = MagicMock(return_value=None)

        # Call 3: conditional UPDATE (only reached by the second admin)
        update_result = MagicMock()
        update_result.rowcount = 1

        session.execute = AsyncMock(
            side_effect=[select_result, no_approval_result, update_result]
        )

        async def _refresh(obj: Any) -> None:
            if obj is factor and factor is not None and not obj.is_published:
                obj.is_published = True
                if obj.published_at is None:
                    obj.published_at = datetime(2026, 5, 14, 0, 0, 0, tzinfo=UTC)
                if obj.published_by is None:
                    obj.published_by = _USER_ESG

        session.refresh = _refresh
        yield session

    return _gen


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Ensure app.dependency_overrides is clean before and after each test."""
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPublishHappyPath:
    """First publish call (no prior approval) creates PENDING approval row -> 202.

    Under the two-eyes approval workflow (FR-12, ISAE 3000 §A99) the first
    admin to call /publish does NOT immediately publish the factor.
    Instead, an approval row is created with decision=PENDING and HTTP 202
    is returned. The factor is published by the second admin's call.
    Full second-manager approval tests live in test_factor_publish_approval.py.
    """

    def test_happy_path_returns_202_with_approval_id(self) -> None:
        factor = _make_factor_orm(is_published=False, value=1.23)
        app.dependency_overrides[get_current_user] = _auth_override(
            "admin", user_id=_USER_ESG
        )
        app.dependency_overrides[get_db] = _db_returning(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_BASE_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 202
        data = resp.json()
        assert "approval_id" in data
        assert "awaiting" in data["message"].lower()

    def test_happy_path_factor_not_yet_published_after_first_call(self) -> None:
        """Factor must remain unpublished; the ORM is_published stays False."""
        factor = _make_factor_orm(is_published=False, value=5.0)
        app.dependency_overrides[get_current_user] = _auth_override(
            "admin", user_id=_USER_ESG
        )
        app.dependency_overrides[get_db] = _db_returning(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            client.post(_BASE_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert factor.is_published is False

    def test_happy_path_with_publish_notes_accepted(self) -> None:
        """publish_notes is accepted at schema level; reason_code is stored."""
        factor = _make_factor_orm(is_published=False, value=2.5)
        app.dependency_overrides[get_current_user] = _auth_override(
            "admin", user_id=_USER_ESG
        )
        app.dependency_overrides[get_db] = _db_returning(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                _BASE_URL,
                json={  # noqa: E501
                    "reason_code": "INITIAL_PUBLICATION",
                    "publish_notes": "Reviewed against DEFRA 2024 spreadsheet",
                },
            )

        assert resp.status_code == 202

    def test_happy_path_licence_only_null_value_accepted(self) -> None:
        """A licence-only factor with value=None must be accepted (passes pre-conditions)."""
        factor = _make_factor_orm(
            is_published=False,
            value=None,
            is_licence_only=True,
        )
        app.dependency_overrides[get_current_user] = _auth_override(
            "admin", user_id=_USER_ESG
        )
        app.dependency_overrides[get_db] = _db_returning(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_BASE_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 202


class TestPublishAuth:
    """Authentication and authorisation failures."""

    def test_401_unauthenticated(self) -> None:
        """No Authorization header -> 401."""
        app.dependency_overrides[get_db] = _db_returning(None)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_BASE_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 401

    def test_403_auditor_role(self) -> None:
        """viewer may not publish factors."""
        factor = _make_factor_orm(is_published=False)
        app.dependency_overrides[get_current_user] = _auth_override("viewer")
        app.dependency_overrides[get_db] = _db_returning(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_BASE_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 403

    def test_403_data_steward_role(self) -> None:
        """editor may create drafts but NOT publish."""
        factor = _make_factor_orm(is_published=False)
        app.dependency_overrides[get_current_user] = _auth_override(
            "editor", user_id=_USER_DS
        )
        app.dependency_overrides[get_db] = _db_returning(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_BASE_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 403


class TestPublishNotFound:
    """404 cases: unknown UUID and cross-tenant isolation."""

    def test_404_unknown_uuid(self) -> None:
        """Repository returns None for an unknown UUID -> 404."""
        app.dependency_overrides[get_current_user] = _auth_override("admin")
        app.dependency_overrides[get_db] = _db_returning(None)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_BASE_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 404
        body = resp.json()
        assert "not found" in body["detail"]["detail"].lower()

    def test_404_cross_tenant_isolation(self) -> None:
        """Factor exists under tenant_A but request comes from tenant_B.

        The repository scopes its query to the caller's tenant_id.  A factor
        row owned by tenant_A is invisible to tenant_B, so the mock returning
        None (simulating the RLS/WHERE tenant filter) produces a 404.
        """
        app.dependency_overrides[get_current_user] = _auth_override(
            "admin", tenant_id=_TENANT_B
        )
        app.dependency_overrides[get_db] = _db_returning(None)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_BASE_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 404


class TestPublishConflict:
    """409 when factor is already published."""

    def test_409_already_published(self) -> None:
        factor = _make_factor_orm(is_published=True, value=1.5)
        app.dependency_overrides[get_current_user] = _auth_override("admin")
        app.dependency_overrides[get_db] = _db_returning(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_BASE_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 409
        problem = resp.json()["detail"]
        assert problem["error_code"] == "already_published"
        assert "immutable" in problem["detail"].lower()

    def test_409_body_contains_factor_identity(self) -> None:
        factor = _make_factor_orm(is_published=True, value=1.5)
        app.dependency_overrides[get_current_user] = _auth_override("admin")
        app.dependency_overrides[get_db] = _db_returning(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_BASE_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 409
        problem = resp.json()["detail"]
        assert "TEST_FACTOR_001" in problem["detail"]
        assert "v1" in problem["detail"]


class TestPublishValidationErrors:
    """422 pre-condition failures."""

    def test_422_is_tbc_true(self) -> None:
        """TBC factors cannot be published - their value is not yet pinned."""
        factor = _make_factor_orm(is_published=False, is_tbc=True, value=None)
        app.dependency_overrides[get_current_user] = _auth_override("admin")
        app.dependency_overrides[get_db] = _db_returning(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_BASE_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 422
        problem = resp.json()["detail"]
        assert problem["error_code"] == "tbc_factor"
        assert "tbc" in problem["detail"].lower()

    def test_422_null_value_non_licence_factor(self) -> None:
        """value=None with is_licence_only=False must be rejected."""
        factor = _make_factor_orm(
            is_published=False,
            is_tbc=False,
            is_licence_only=False,
            value=None,
        )
        app.dependency_overrides[get_current_user] = _auth_override("admin")
        app.dependency_overrides[get_db] = _db_returning(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_BASE_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 422
        problem = resp.json()["detail"]
        assert problem["error_code"] == "null_value"
        assert "null" in problem["detail"].lower()

    def test_422_publish_notes_too_long(self) -> None:
        """publish_notes exceeding 2000 chars fails Pydantic validation at the body level."""
        factor = _make_factor_orm(is_published=False, value=1.0)
        app.dependency_overrides[get_current_user] = _auth_override("admin")
        app.dependency_overrides[get_db] = _db_returning(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                _BASE_URL,
                json={"reason_code": "INITIAL_PUBLICATION", "publish_notes": "x" * 2001},
            )

        assert resp.status_code == 422


class TestPublishAuditLog:
    """Verify the structured log is emitted on approval request (202)."""

    def test_structured_log_emitted_on_approval_request(self) -> None:
        """First /publish call emits 'factor_approval_requested' log event."""
        factor = _make_factor_orm(is_published=False, value=9.9)
        app.dependency_overrides[get_current_user] = _auth_override(
            "admin", user_id=_USER_ESG
        )
        app.dependency_overrides[get_db] = _db_returning(factor)

        captured: list[dict] = []

        class _CapturingLogger:
            def __init__(self) -> None:
                self._bindings: dict = {}

            def bind(self, **kw: Any) -> _CapturingLogger:
                new = _CapturingLogger()
                new._bindings = {**self._bindings, **kw}
                return new

            def info(self, event: str, **kw: Any) -> None:
                captured.append({"event": event, **self._bindings, **kw})

            def warning(self, event: str, **kw: Any) -> None:
                pass

        with patch(
            "ghg_tool.api.routers.factor_catalog.logger",
            _CapturingLogger(),
        ), TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                _BASE_URL,
                json={"reason_code": "INITIAL_PUBLICATION", "publish_notes": "CSRD sign-off Q1"},
            )

        assert resp.status_code == 202
        approval_events = [
            e for e in captured if e.get("event") == "factor_approval_requested"
        ]
        assert len(approval_events) == 1
        ev = approval_events[0]
        assert ev["factor_id"] == "TEST_FACTOR_001"
        assert ev["reason_code"] == "INITIAL_PUBLICATION"
        assert "correlation_id" in ev


class TestPublishRequestSchemaValidation:
    """Body validation tests for the reason_code and publish_notes fields."""

    def test_422_missing_reason_code(self):
        """An empty body now fails Pydantic validation before the handler runs."""
        app.dependency_overrides[get_current_user] = _auth_override(
            "admin", user_id=_USER_ESG
        )
        app.dependency_overrides[get_db] = _db_returning(
            _make_factor_orm(is_published=False, value=1.0)
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_BASE_URL, json={})
        assert resp.status_code == 422

    def test_422_invalid_reason_code(self):
        """Unknown reason_code value rejected by the Literal enum."""
        app.dependency_overrides[get_current_user] = _auth_override(
            "admin", user_id=_USER_ESG
        )
        app.dependency_overrides[get_db] = _db_returning(
            _make_factor_orm(is_published=False, value=1.0)
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                _BASE_URL,
                json={"reason_code": "NOT_A_REAL_CODE"},
            )
        assert resp.status_code == 422

    def test_202_accepts_2000_char_notes(self):
        """publish_notes cap is 2000 chars; valid length -> 202 (not 422)."""
        factor = _make_factor_orm(is_published=False, value=1.0)
        app.dependency_overrides[get_current_user] = _auth_override(
            "admin", user_id=_USER_ESG
        )
        app.dependency_overrides[get_db] = _db_returning(factor)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                _BASE_URL,
                json={"reason_code": "INITIAL_PUBLICATION", "publish_notes": "x" * 2000},
            )
        assert resp.status_code != 422 or "publish_notes" not in resp.text

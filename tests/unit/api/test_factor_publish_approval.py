"""Unit tests for the two-eyes factor publish approval workflow (#12).

Covers:
- 202: first admin calls /publish -> approval row created PENDING
- 409: same admin calls /publish again -> self_approval_forbidden
- 200: second admin calls /publish -> factor published, approval APPROVED
- 409: third call after approval -> already_published
- 200: list pending approvals
- 200: reject approval, factor remains draft
- 403: editor calls /publish
- 422: rejection_reason < 10 chars

All DB access is mocked; no live PostgreSQL instance required.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

import pytest
from fastapi.testclient import TestClient

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.main import app
from ghg_tool.infrastructure.db.models.factor_publish_approval import FactorPublishApproval

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TENANT = str(uuid.uuid4())
_ESG1 = str(uuid.uuid4())
_ESG2 = str(uuid.uuid4())
_DS = str(uuid.uuid4())
_FACTOR_UUID = uuid.uuid4()
_APPROVAL_UUID = uuid.uuid4()

_PUBLISH_URL = f"/api/v1/factor-catalog/{_FACTOR_UUID}/publish"
_PENDING_URL = "/api/v1/factor-catalog/pending-approvals"
_REJECT_URL = f"/api/v1/factor-catalog/approvals/{_APPROVAL_UUID}/reject"

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


def _make_factor_orm(
    *,
    is_published: bool = False,
    is_tbc: bool = False,
    is_licence_only: bool = False,
    value: float | None = 1.23,
    factor_uuid: uuid.UUID = _FACTOR_UUID,
) -> MagicMock:
    factor = MagicMock()
    factor.id = factor_uuid
    factor.tenant_id = uuid.UUID(_TENANT)
    factor.factor_id = "TEST_FACTOR_APPROVAL_001"
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
    factor.published_at = datetime(2026, 1, 1, tzinfo=UTC) if is_published else None
    factor.published_by = _ESG2 if is_published else None
    factor.is_published = is_published
    factor.biogenic_co2_kg_per_unit = None
    return factor


def _make_approval_orm(
    *,
    proposed_by: str = _ESG1,
    decision: str = "PENDING",
    approval_id: uuid.UUID = _APPROVAL_UUID,
    factor_id: uuid.UUID = _FACTOR_UUID,
) -> MagicMock:
    approval = MagicMock(spec=FactorPublishApproval)
    approval.id = approval_id
    approval.tenant_id = uuid.UUID(_TENANT)
    approval.factor_id = factor_id
    approval.proposed_by = uuid.UUID(proposed_by)
    approval.proposed_at = datetime(2026, 5, 1, tzinfo=UTC)
    approval.decision = decision
    approval.approved_by = None
    approval.approved_at = None
    approval.decision_notes = None
    approval.reason_code = "INITIAL_PUBLICATION"
    approval.correlation_id = uuid.uuid4()
    return approval


def _db_first_publish(factor: MagicMock) -> Any:
    """DB for first /publish call: no existing approval, draft factor.

    execute() calls:
      1. FactorCatalogRepository.get_by_uuid (SELECT scalar_one_or_none)
      2. _get_pending_approval (SELECT scalar_one_or_none -> None)
    session.add + flush for new approval row.
    """
    async def _gen() -> Any:
        session = AsyncMock()
        session.flush = AsyncMock(return_value=None)
        session.add = MagicMock(return_value=None)

        # Call 1: repo.get_by_uuid -> factor
        select_factor = MagicMock()
        select_factor.scalar_one_or_none = MagicMock(return_value=factor)

        # Call 2: _get_pending_approval -> None
        select_approval = MagicMock()
        select_approval.scalar_one_or_none = MagicMock(return_value=None)

        session.execute = AsyncMock(
            side_effect=[select_factor, select_approval]
        )
        yield session

    return _gen


def _db_self_approval(factor: MagicMock, approval: MagicMock) -> Any:
    """DB for second /publish by the same proposer -> PENDING exists, same user."""
    async def _gen() -> Any:
        session = AsyncMock()
        session.flush = AsyncMock(return_value=None)
        session.add = MagicMock(return_value=None)

        select_factor = MagicMock()
        select_factor.scalar_one_or_none = MagicMock(return_value=factor)

        select_approval = MagicMock()
        select_approval.scalar_one_or_none = MagicMock(return_value=approval)

        session.execute = AsyncMock(
            side_effect=[select_factor, select_approval]
        )
        yield session

    return _gen


def _db_second_esg_publish(factor: MagicMock, approval: MagicMock) -> Any:
    """DB for second admin /publish: PENDING by ESG1, caller is ESG2.

    execute() calls:
      1. repo.get_by_uuid -> factor (draft)
      2. _get_pending_approval -> pending approval (proposed_by=ESG1)
      3. conditional UPDATE on factor_catalog -> rowcount=1
    refresh: flips is_published.
    """
    async def _gen() -> Any:
        session = AsyncMock()
        session.flush = AsyncMock(return_value=None)
        session.add = MagicMock(return_value=None)

        select_factor = MagicMock()
        select_factor.scalar_one_or_none = MagicMock(return_value=factor)

        select_approval = MagicMock()
        select_approval.scalar_one_or_none = MagicMock(return_value=approval)

        update_result = MagicMock()
        update_result.rowcount = 1

        session.execute = AsyncMock(
            side_effect=[select_factor, select_approval, update_result]
        )

        async def _refresh(obj: Any) -> None:
            if obj is factor and not obj.is_published:
                obj.is_published = True
                obj.published_at = datetime(2026, 5, 14, tzinfo=UTC)
                obj.published_by = _ESG2

        session.refresh = _refresh
        yield session

    return _gen


def _db_already_published(factor: MagicMock) -> Any:
    """DB for any call when factor is already published."""
    async def _gen() -> Any:
        session = AsyncMock()
        session.flush = AsyncMock(return_value=None)
        session.add = MagicMock(return_value=None)

        select_factor = MagicMock()
        select_factor.scalar_one_or_none = MagicMock(return_value=factor)

        session.execute = AsyncMock(return_value=select_factor)
        yield session

    return _gen


def _db_pending_list(rows: list[Any]) -> Any:
    """DB for GET /pending-approvals."""
    async def _gen() -> Any:
        session = AsyncMock()
        result = MagicMock()
        result.fetchall = MagicMock(return_value=rows)
        session.execute = AsyncMock(return_value=result)
        yield session

    return _gen


def _db_reject(approval: MagicMock | None) -> Any:
    """DB for POST /approvals/{uuid}/reject."""
    async def _gen() -> Any:
        session = AsyncMock()
        session.flush = AsyncMock(return_value=None)
        session.add = MagicMock(return_value=None)

        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=approval)

        session.execute = AsyncMock(return_value=select_result)
        yield session

    return _gen


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_overrides() -> Any:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFirstPublishRequestCreatesApproval:
    """Happy path: first admin calls /publish -> 202, PENDING row created."""

    def test_first_call_returns_202_with_approval_id(self) -> None:
        factor = _make_factor_orm(is_published=False)
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        app.dependency_overrides[get_db] = _db_first_publish(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_PUBLISH_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 202
        data = resp.json()
        assert "approval_id" in data
        assert "awaiting" in data["message"].lower()

    def test_first_call_session_add_called_for_approval_and_audit(self) -> None:
        """session.add must be called at least twice: approval row + audit log."""
        factor = _make_factor_orm(is_published=False)
        adds: list[Any] = []

        async def _gen() -> Any:
            session = AsyncMock()
            session.flush = AsyncMock(return_value=None)

            def _capture(obj: Any) -> None:
                adds.append(obj)

            session.add = MagicMock(side_effect=_capture)

            sel_factor = MagicMock()
            sel_factor.scalar_one_or_none = MagicMock(return_value=factor)
            sel_approval = MagicMock()
            sel_approval.scalar_one_or_none = MagicMock(return_value=None)
            session.execute = AsyncMock(side_effect=[sel_factor, sel_approval])
            yield session

        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        app.dependency_overrides[get_db] = _gen

        with TestClient(app, raise_server_exceptions=False) as client:
            client.post(_PUBLISH_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert len(adds) >= 2


class TestSelfApprovalForbidden:
    """409 when the same admin who proposed tries to approve."""

    def test_same_proposer_gets_409_self_approval_forbidden(self) -> None:
        factor = _make_factor_orm(is_published=False)
        # Approval was proposed by _ESG1, caller is also _ESG1
        approval = _make_approval_orm(proposed_by=_ESG1, decision="PENDING")
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        app.dependency_overrides[get_db] = _db_self_approval(factor, approval)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_PUBLISH_URL, json={"reason_code": "VERSION_BUMP"})

        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "self_approval_forbidden"


class TestSecondEsgManagerApproves:
    """Happy path: second admin calls /publish -> 200, factor published."""

    def test_second_esg_manager_gets_200_is_published_true(self) -> None:
        factor = _make_factor_orm(is_published=False)
        approval = _make_approval_orm(proposed_by=_ESG1, decision="PENDING")
        # Caller is _ESG2 (different from proposer _ESG1)
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG2)
        app.dependency_overrides[get_db] = _db_second_esg_publish(factor, approval)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_PUBLISH_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 200
        assert resp.json()["is_published"] is True


class TestAlreadyPublished:
    """409 when the factor is already published."""

    def test_third_call_returns_409_already_published(self) -> None:
        factor = _make_factor_orm(is_published=True)
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG2)
        app.dependency_overrides[get_db] = _db_already_published(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_PUBLISH_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 409
        assert resp.json()["detail"]["error_code"] == "already_published"


class TestListPendingApprovals:
    """GET /pending-approvals - list pending approvals for the tenant."""

    def test_returns_pending_approvals_list(self) -> None:
        row = MagicMock()
        row.id = _APPROVAL_UUID
        row.factor_id = _FACTOR_UUID
        row.factor_string_id = "TEST_FACTOR_001"
        row.proposed_by = uuid.UUID(_ESG1)
        row.proposed_at = datetime(2026, 5, 1, tzinfo=UTC)
        row.reason_code = "INITIAL_PUBLICATION"

        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        app.dependency_overrides[get_db] = _db_pending_list([row])

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(_PENDING_URL)

        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["approval_id"] == str(_APPROVAL_UUID)
        assert items[0]["reason_code"] == "INITIAL_PUBLICATION"

    def test_403_data_steward_cannot_list_approvals(self) -> None:
        app.dependency_overrides[get_current_user] = _auth("editor", _DS)
        app.dependency_overrides[get_db] = _db_pending_list([])

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(_PENDING_URL)

        assert resp.status_code == 403


class TestRejectApproval:
    """POST /approvals/{uuid}/reject."""

    def test_happy_path_reject_returns_200_decision_rejected(self) -> None:
        approval = _make_approval_orm(proposed_by=_ESG1, decision="PENDING")
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG2)
        app.dependency_overrides[get_db] = _db_reject(approval)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                _REJECT_URL,
                json={"rejection_reason": "Factor source is not verified."},
            )

        assert resp.status_code == 200
        assert resp.json()["decision"] == "REJECTED"

    def test_happy_path_reject_sets_decision_on_approval_orm(self) -> None:
        """After rejection the ORM object's decision attribute is REJECTED."""
        approval = _make_approval_orm(proposed_by=_ESG1, decision="PENDING")
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG2)
        app.dependency_overrides[get_db] = _db_reject(approval)

        with TestClient(app, raise_server_exceptions=False) as client:
            client.post(
                _REJECT_URL,
                json={"rejection_reason": "Methodology not aligned with CSRD."},
            )

        assert approval.decision == "REJECTED"
        assert approval.decision_notes == "Methodology not aligned with CSRD."

    def test_422_rejection_reason_too_short(self) -> None:
        """rejection_reason shorter than 10 chars -> 422 from Pydantic."""
        approval = _make_approval_orm(proposed_by=_ESG1, decision="PENDING")
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG2)
        app.dependency_overrides[get_db] = _db_reject(approval)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_REJECT_URL, json={"rejection_reason": "Too short"})

        assert resp.status_code == 422

    def test_404_unknown_approval(self) -> None:
        """Unknown approval UUID -> 404."""
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG2)
        app.dependency_overrides[get_db] = _db_reject(None)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                _REJECT_URL,
                json={"rejection_reason": "Reason longer than ten characters."},
            )

        assert resp.status_code == 404


class TestPublishRbac:
    """RBAC enforcement on /publish."""

    def test_403_data_steward_cannot_publish(self) -> None:
        """editor may not call /publish -> 403."""
        factor = _make_factor_orm(is_published=False)
        app.dependency_overrides[get_current_user] = _auth("editor", _DS)
        app.dependency_overrides[get_db] = _db_first_publish(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_PUBLISH_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 403

    def test_401_unauthenticated(self) -> None:
        """No token -> 401."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_PUBLISH_URL, json={"reason_code": "INITIAL_PUBLICATION"})
        assert resp.status_code == 401

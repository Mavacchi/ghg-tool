"""Unit tests for MG-03 schema changes on ref.factor_catalog (migration 0010_M9).

These tests use mocked DB sessions and mocked repository calls -- no live
PostgreSQL is required.  They verify:
  1. POST /api/v1/factor-catalog/ returns published_at=None and
     published_by=None for a freshly created draft.
  2. The publish endpoint then sets both to non-None.

NOTE: The DB-level CHECK constraint
  (is_published = false)
  OR (is_published = true AND published_at IS NOT NULL AND published_by IS NOT NULL)
is exercised only by integration/migration tests that run against a real
PostgreSQL instance.  That gap is documented as TEST-GAP-MG03-CHECK.
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
from ghg_tool.infrastructure.db.models.factor_publish_approval import FactorPublishApproval

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TENANT_A = str(uuid.uuid4())
_USER_DS = str(uuid.uuid4())
_USER_ESG = str(uuid.uuid4())   # second esg_manager: the approver in the 200-flow
_USER_ESG_PROPOSER = str(uuid.uuid4())  # first esg_manager: proposed the PENDING row
_FACTOR_UUID = uuid.uuid4()
_APPROVAL_UUID = uuid.uuid4()

_CREATE_URL = "/api/v1/factor-catalog/"
_PUBLISH_URL = f"/api/v1/factor-catalog/{_FACTOR_UUID}/publish"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str, user_id: str | None = None) -> CurrentUser:
    return CurrentUser(
        sub=user_id or str(uuid.uuid4()),
        role=role,  # type: ignore[arg-type]
        tenant_id=_TENANT_A,
        jti=str(uuid.uuid4()),
    )


def _auth_override(role: str, user_id: str | None = None) -> Any:
    user = _make_user(role, user_id=user_id)

    async def _dep() -> CurrentUser:
        return user

    return _dep


def _make_draft_orm(factor_uuid: uuid.UUID = _FACTOR_UUID) -> MagicMock:
    """Return an ORM-like MagicMock representing a freshly inserted draft row.

    MG-03: draft rows have published_at=None and published_by=None.
    created_at is set to the INSERT time.
    """
    factor = MagicMock()
    factor.id = factor_uuid
    factor.tenant_id = uuid.UUID(_TENANT_A)
    factor.factor_id = "MG03_TEST_FACTOR"
    factor.version = "v1"
    factor.substance = "CO2"
    factor.scope = 1
    factor.category = "combustion"
    factor.source = "DEFRA"
    factor.value = 2.5
    factor.is_licence_only = False
    factor.is_tbc = False
    factor.unit = "kgCO2e/kWh"
    factor.gwp_set = "AR6"
    factor.vintage = "2025"
    factor.valid_from = date(2025, 1, 1)
    factor.valid_to = None
    factor.applicability_note = None
    factor.pdf_source_uri = None
    factor.biogenic_co2_kg_per_unit = None
    # MG-03 fields
    factor.created_at = datetime(2025, 5, 14, 12, 0, 0, tzinfo=UTC)
    factor.published_at = None
    factor.published_by = None
    factor.is_published = False
    return factor


def _make_published_orm(factor_uuid: uuid.UUID = _FACTOR_UUID) -> MagicMock:
    """Return an ORM-like MagicMock representing a published row.

    MG-03: published rows have published_at and published_by set to non-None.
    """
    factor = _make_draft_orm(factor_uuid)
    factor.is_published = True
    factor.published_at = datetime(2025, 5, 14, 14, 0, 0, tzinfo=UTC)
    factor.published_by = _USER_ESG
    return factor


def _db_for_create(persisted_factor: MagicMock) -> Any:
    """Mock a DB session whose repository insert returns *persisted_factor*."""

    async def _gen() -> Any:
        session = AsyncMock()
        session.flush = AsyncMock(return_value=None)
        session.refresh = AsyncMock(return_value=None)
        # The repository's insert calls session.add + session.flush + session.refresh.
        session.add = MagicMock(return_value=None)

        async def _refresh(obj: Any) -> None:
            # After refresh the persisted state is the mock itself; no-op.
            pass

        session.refresh = _refresh
        # Patch the repository insert to return the mock directly.
        with patch(
            "ghg_tool.infrastructure.db.repositories.factor_catalog_repository"
            ".FactorCatalogRepository.insert",
            new=AsyncMock(return_value=persisted_factor),
        ):
            yield session

    return _gen


def _make_approval_orm(
    *,
    proposed_by: str = _USER_ESG_PROPOSER,
    decision: str = "PENDING",
    approval_id: uuid.UUID = _APPROVAL_UUID,
    factor_id: uuid.UUID = _FACTOR_UUID,
) -> MagicMock:
    """Return an ORM-like MagicMock for a FactorPublishApproval row."""
    approval = MagicMock(spec=FactorPublishApproval)
    approval.id = approval_id
    approval.tenant_id = uuid.UUID(_TENANT_A)
    approval.factor_id = factor_id
    approval.proposed_by = uuid.UUID(proposed_by)
    approval.proposed_at = datetime(2025, 5, 14, 12, 30, 0, tzinfo=UTC)
    approval.decision = decision
    approval.approved_by = None
    approval.approved_at = None
    approval.decision_notes = None
    approval.reason_code = "INITIAL_PUBLICATION"
    approval.correlation_id = uuid.uuid4()
    return approval


def _db_for_publish_second_call(
    draft_factor: MagicMock,
    pending_approval: MagicMock,
    published_factor: MagicMock,
) -> Any:
    """Mock a DB session for the TWO-EYES publish 200-flow.

    Models the case where a PENDING approval already exists (proposed by
    _USER_ESG_PROPOSER) and a *different* esg_manager (_USER_ESG) calls
    POST /publish to approve.

    session.execute side_effect (in order):
      1. repo.get_by_uuid SELECT -> scalar_one_or_none -> draft_factor
      2. _get_pending_approval SELECT -> scalar_one_or_none -> pending_approval
      3. _do_publish conditional UPDATE -> rowcount=1

    After session.refresh(factor) the factor object is updated to reflect
    the published state (simulating the DB returning post-UPDATE values).
    """

    async def _gen() -> Any:
        session = AsyncMock()
        session.flush = AsyncMock(return_value=None)
        session.add = MagicMock(return_value=None)

        # Call 1: repo.get_by_uuid -> draft factor
        select_factor = MagicMock()
        select_factor.scalar_one_or_none = MagicMock(return_value=draft_factor)

        # Call 2: _get_pending_approval -> PENDING approval row
        select_approval = MagicMock()
        select_approval.scalar_one_or_none = MagicMock(return_value=pending_approval)

        # Call 3: conditional UPDATE on factor_catalog -> rowcount=1
        update_result = MagicMock()
        update_result.rowcount = 1

        session.execute = AsyncMock(
            side_effect=[select_factor, select_approval, update_result]
        )

        async def _refresh(obj: Any) -> None:
            # Simulate DB returning post-UPDATE state for the factor row.
            obj.is_published = published_factor.is_published
            obj.published_at = published_factor.published_at
            obj.published_by = published_factor.published_by

        session.refresh = _refresh
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


class TestDraftCreateHasNullPublishFields:
    """POST /factor-catalog/ draft row must return published_at=None, published_by=None."""

    def test_draft_response_has_null_published_at(self) -> None:
        """MG-03: published_at must be None on a freshly created draft."""
        draft = _make_draft_orm()
        app.dependency_overrides[get_current_user] = _auth_override(
            "data_steward", user_id=_USER_DS
        )
        app.dependency_overrides[get_db] = _db_for_create(draft)

        payload = {
            "factor_id": "MG03_TEST_FACTOR",
            "version": "v1",
            "substance": "CO2",
            "scope": 1,
            "category": "combustion",
            "source": "DEFRA",
            "value": 2.5,
            "unit": "kgCO2e/kWh",
            "gwp_set": "AR6",
            "valid_from": "2025-01-01",
        }

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_CREATE_URL, json=payload)

        assert resp.status_code == 201
        data = resp.json()
        assert data["published_at"] is None, (
            "MG-03: draft published_at must be None"
        )
        assert data["published_by"] is None, (
            "MG-03: draft published_by must be None"
        )
        assert data["is_published"] is False
        assert data["created_at"] is not None, (
            "MG-03: created_at must always be present"
        )

    def test_draft_response_has_null_published_by(self) -> None:
        """published_by must be None for a draft (not the creator sub)."""
        draft = _make_draft_orm()
        app.dependency_overrides[get_current_user] = _auth_override(
            "data_steward", user_id=_USER_DS
        )
        app.dependency_overrides[get_db] = _db_for_create(draft)

        payload = {
            "factor_id": "MG03_TEST_FACTOR",
            "version": "v1",
            "substance": "CO2",
            "scope": 1,
            "category": "combustion",
            "source": "DEFRA",
            "value": 2.5,
            "unit": "kgCO2e/kWh",
            "gwp_set": "AR6",
            "valid_from": "2025-01-01",
        }

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_CREATE_URL, json=payload)

        assert resp.status_code == 201
        assert resp.json()["published_by"] is None


class TestPublishSetsPublishFields:
    """Publish endpoint must set published_at and published_by to non-None.

    All tests drive the two-eyes ISAE-3000 §A99 200-flow:
    - A PENDING approval was created by _USER_ESG_PROPOSER (first esg_manager).
    - The test client calls POST /publish as _USER_ESG (second, different esg_manager).
    - Expected outcome: HTTP 200, factor published.
    """

    def test_publish_sets_published_at_non_null(self) -> None:
        """After publish (second esg_manager approves), published_at must be non-None."""
        draft = _make_draft_orm()
        pending = _make_approval_orm(proposed_by=_USER_ESG_PROPOSER)
        published = _make_published_orm()
        # Caller is _USER_ESG — DIFFERENT from the proposer _USER_ESG_PROPOSER.
        app.dependency_overrides[get_current_user] = _auth_override(
            "esg_manager", user_id=_USER_ESG
        )
        app.dependency_overrides[get_db] = _db_for_publish_second_call(
            draft, pending, published
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_PUBLISH_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_published"] is True
        assert data["published_at"] is not None, (
            "MG-03: published_at must be non-None after publish"
        )
        assert data["published_by"] is not None, (
            "MG-03: published_by must be non-None after publish"
        )
        assert data["created_at"] is not None, (
            "MG-03: created_at must always be present"
        )

    def test_publish_sets_published_by_to_caller_uuid(self) -> None:
        """published_by must equal the UUID of the approving esg_manager."""
        draft = _make_draft_orm()
        pending = _make_approval_orm(proposed_by=_USER_ESG_PROPOSER)
        published = _make_published_orm()
        # Caller is _USER_ESG; published_by on the refreshed ORM object must
        # match _USER_ESG (set by _make_published_orm / _refresh in the mock).
        app.dependency_overrides[get_current_user] = _auth_override(
            "esg_manager", user_id=_USER_ESG
        )
        app.dependency_overrides[get_db] = _db_for_publish_second_call(
            draft, pending, published
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_PUBLISH_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_published"] is True
        assert data["published_by"] == _USER_ESG, (
            "MG-03: published_by must be the UUID of the approving esg_manager"
        )

    def test_published_factor_response_has_all_mg03_fields(self) -> None:
        """Response after publish must carry is_published, published_at,
        published_by, and created_at — all non-None (MG-03 schema contract)."""
        draft = _make_draft_orm()
        pending = _make_approval_orm(proposed_by=_USER_ESG_PROPOSER)
        published = _make_published_orm()
        app.dependency_overrides[get_current_user] = _auth_override(
            "esg_manager", user_id=_USER_ESG
        )
        app.dependency_overrides[get_db] = _db_for_publish_second_call(
            draft, pending, published
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(_PUBLISH_URL, json={"reason_code": "INITIAL_PUBLICATION"})

        assert resp.status_code == 200
        data = resp.json()
        # MG-03 mandatory fields on a published factor:
        assert data["is_published"] is True
        assert data["published_at"] is not None, (
            "MG-03: published_at must be set after publish"
        )
        assert data["published_by"] is not None, (
            "MG-03: published_by must be set after publish"
        )
        assert data["created_at"] is not None, (
            "MG-03: created_at must always be present"
        )

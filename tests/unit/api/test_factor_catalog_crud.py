"""Unit tests for PATCH and DELETE /api/v1/factor-catalog/{factor_uuid}.

Covers CRUD operations on DRAFT factor rows (is_published=False).
Published rows are immutable per ADR-007 / ISAE 3000 §A99 and must be
refused with 422 factor_already_published.

Test matrix:
- test_patch_draft_value_returns_200
- test_patch_draft_only_subset_fields
- test_patch_published_returns_422_factor_already_published
- test_patch_cross_tenant_returns_404
- test_patch_audit_log_row_written
- test_delete_draft_returns_204
- test_delete_published_returns_422
- test_delete_unknown_returns_404
- test_delete_cross_tenant_returns_404
- test_patch_unauth_role_returns_403 (auditor, esg_manager)
- test_delete_unauth_role_returns_403

All DB access is mocked via dependency_overrides. No live PostgreSQL
instance is required.
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TENANT_A = str(uuid.uuid4())
_TENANT_B = str(uuid.uuid4())
_USER_DS = str(uuid.uuid4())      # data_steward
_USER_ESG = str(uuid.uuid4())     # esg_manager
_USER_AU = str(uuid.uuid4())      # auditor
_FACTOR_UUID = uuid.uuid4()

_PATCH_URL = f"/api/v1/factor-catalog/{_FACTOR_UUID}"
_DELETE_URL = f"/api/v1/factor-catalog/{_FACTOR_UUID}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    role: str,
    tenant_id: str = _TENANT_A,
    user_id: str | None = None,
) -> CurrentUser:
    return CurrentUser(
        sub=user_id or str(uuid.uuid4()),
        role=role,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        jti=str(uuid.uuid4()),
    )


def _auth_override(
    role: str,
    tenant_id: str = _TENANT_A,
    user_id: str | None = None,
) -> Any:
    user = _make_user(role, tenant_id=tenant_id, user_id=user_id)

    async def _dep() -> CurrentUser:
        return user

    return _dep


def _make_factor_orm(
    *,
    factor_uuid: uuid.UUID = _FACTOR_UUID,
    tenant_id: str = _TENANT_A,
    is_published: bool = False,
    value: float | None = 1.23,
    unit: str = "kgCO2e/kWh",
    applicability_note: str | None = None,
    is_licence_only: bool = False,
    is_tbc: bool = False,
    vintage: str | None = "2024",
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
    factor.unit = unit
    factor.gwp_set = "AR6"
    factor.vintage = vintage
    factor.valid_from = date(2024, 1, 1)
    factor.valid_to = None
    factor.applicability_note = applicability_note
    factor.pdf_source_uri = None
    factor.created_at = datetime(2024, 1, 1, tzinfo=UTC)
    factor.published_at = datetime(2024, 1, 1, tzinfo=UTC) if is_published else None
    factor.published_by = "esg-manager-user" if is_published else None
    factor.is_published = is_published
    factor.biogenic_co2_kg_per_unit = None
    return factor


def _db_for_patch(factor: MagicMock | None) -> Any:
    """Build an async DB session override for PATCH tests.

    Query order inside patch_factor:
      1. SELECT via FactorCatalogRepository.get_by_uuid
      2. session.flush() after setattr updates
      3. session.add(AuditLog) + session.flush() for audit row
    """

    async def _gen() -> Any:
        session = AsyncMock()
        session.add = MagicMock(return_value=None)

        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=factor)

        session.execute = AsyncMock(side_effect=[select_result])
        session.flush = AsyncMock(return_value=None)

        yield session

    return _gen


def _db_for_delete(factor: MagicMock | None) -> Any:
    """Build an async DB session override for DELETE tests.

    Query order inside delete_factor:
      1. SELECT via FactorCatalogRepository.get_by_uuid
      2. session.delete(factor)
      3. session.add(AuditLog) + session.flush()
    """

    async def _gen() -> Any:
        session = AsyncMock()
        session.add = MagicMock(return_value=None)
        session.delete = AsyncMock(return_value=None)

        select_result = MagicMock()
        select_result.scalar_one_or_none = MagicMock(return_value=factor)

        session.execute = AsyncMock(side_effect=[select_result])
        session.flush = AsyncMock(return_value=None)

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
# PATCH tests
# ---------------------------------------------------------------------------


class TestPatchDraft:
    """Happy-path PATCH tests on draft factor rows."""

    def test_patch_draft_value_returns_200(self) -> None:
        """PATCH with a new value on a draft factor returns 200 with updated row."""
        factor = _make_factor_orm(is_published=False, value=1.23)
        app.dependency_overrides[get_current_user] = _auth_override(
            "data_steward", user_id=_USER_DS
        )
        app.dependency_overrides[get_db] = _db_for_patch(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(_PATCH_URL, json={"value": 9.99})

        assert resp.status_code == 200
        data = resp.json()
        # The mock ORM row is mutated in-place by setattr; model_validate reads it back.
        assert "id" in data
        assert "factor_id" in data

    def test_patch_draft_only_subset_fields(self) -> None:
        """PATCH with only applicability_note leaves other fields untouched."""
        factor = _make_factor_orm(is_published=False, value=5.0, unit="kgCO2e/kWh")
        app.dependency_overrides[get_current_user] = _auth_override(
            "data_steward", user_id=_USER_DS
        )
        app.dependency_overrides[get_db] = _db_for_patch(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(_PATCH_URL, json={"applicability_note": "UK only, post-2023"})

        assert resp.status_code == 200
        # Verify applicability_note was set on the mock
        assert factor.applicability_note == "UK only, post-2023"
        # unit was not in the patch body, so it must remain unchanged
        assert factor.unit == "kgCO2e/kWh"

    def test_patch_audit_log_row_written(self) -> None:
        """PATCH must write an AuditLog row via session.add."""
        factor = _make_factor_orm(is_published=False, value=1.0)
        app.dependency_overrides[get_current_user] = _auth_override(
            "data_steward", user_id=_USER_DS
        )

        add_calls: list[Any] = []

        async def _gen() -> Any:
            session = AsyncMock()
            session.flush = AsyncMock(return_value=None)

            def _record_add(obj: Any) -> None:
                add_calls.append(obj)

            session.add = MagicMock(side_effect=_record_add)

            select_result = MagicMock()
            select_result.scalar_one_or_none = MagicMock(return_value=factor)
            session.execute = AsyncMock(side_effect=[select_result])

            yield session

        app.dependency_overrides[get_db] = _gen

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(_PATCH_URL, json={"unit": "tCO2e/GJ"})

        assert resp.status_code == 200
        from ghg_tool.infrastructure.db.models.audit_log import AuditLog
        audit_rows = [c for c in add_calls if isinstance(c, AuditLog)]
        assert len(audit_rows) == 1
        assert audit_rows[0].action == "factor_draft_updated"
        assert audit_rows[0].request_method == "PATCH"


class TestPatchPublished:
    """PATCH on a published row must return 422 factor_already_published."""

    def test_patch_published_returns_422_factor_already_published(self) -> None:
        factor = _make_factor_orm(is_published=True, value=1.5)
        app.dependency_overrides[get_current_user] = _auth_override(
            "data_steward", user_id=_USER_DS
        )
        app.dependency_overrides[get_db] = _db_for_patch(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(_PATCH_URL, json={"value": 2.0})

        assert resp.status_code == 422
        problem = resp.json()["detail"]
        assert problem["error_code"] == "factor_already_published"
        assert "immutable" in problem["detail"].lower()


class TestPatchNotFound:
    """404 cases: unknown UUID and cross-tenant isolation."""

    def test_patch_cross_tenant_returns_404(self) -> None:
        """Factor owned by tenant_A is invisible to tenant_B -> 404."""
        app.dependency_overrides[get_current_user] = _auth_override(
            "data_steward", tenant_id=_TENANT_B, user_id=_USER_DS
        )
        # Repository returns None for the cross-tenant query.
        app.dependency_overrides[get_db] = _db_for_patch(None)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(_PATCH_URL, json={"value": 3.0})

        assert resp.status_code == 404
        problem = resp.json()["detail"]
        assert problem["error_code"] == "factor_not_found"


class TestPatchAuth:
    """Authentication and authorisation failures for PATCH."""

    @pytest.mark.parametrize("role", ["auditor", "esg_manager"])
    def test_patch_unauth_role_returns_403(self, role: str) -> None:
        """auditor and esg_manager do not have factor_catalog:write -> 403."""
        factor = _make_factor_orm(is_published=False)
        app.dependency_overrides[get_current_user] = _auth_override(role)
        app.dependency_overrides[get_db] = _db_for_patch(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(_PATCH_URL, json={"value": 1.0})

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE tests
# ---------------------------------------------------------------------------


class TestDeleteDraft:
    """Happy-path DELETE tests on draft factor rows."""

    def test_delete_draft_returns_204(self) -> None:
        """DELETE on a draft factor returns 204 No Content."""
        factor = _make_factor_orm(is_published=False, value=1.23)
        app.dependency_overrides[get_current_user] = _auth_override(
            "data_steward", user_id=_USER_DS
        )
        app.dependency_overrides[get_db] = _db_for_delete(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.delete(_DELETE_URL)

        assert resp.status_code == 204
        assert resp.content == b""


class TestDeletePublished:
    """DELETE on a published row must return 422 factor_already_published."""

    def test_delete_published_returns_422(self) -> None:
        factor = _make_factor_orm(is_published=True, value=1.5)
        app.dependency_overrides[get_current_user] = _auth_override(
            "data_steward", user_id=_USER_DS
        )
        app.dependency_overrides[get_db] = _db_for_delete(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.delete(_DELETE_URL)

        assert resp.status_code == 422
        problem = resp.json()["detail"]
        assert problem["error_code"] == "factor_already_published"
        assert "immutable" in problem["detail"].lower()


class TestDeleteNotFound:
    """404 cases: unknown UUID and cross-tenant isolation."""

    def test_delete_unknown_returns_404(self) -> None:
        """Repository returns None for an unknown UUID -> 404."""
        app.dependency_overrides[get_current_user] = _auth_override(
            "data_steward", user_id=_USER_DS
        )
        app.dependency_overrides[get_db] = _db_for_delete(None)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.delete(_DELETE_URL)

        assert resp.status_code == 404
        problem = resp.json()["detail"]
        assert problem["error_code"] == "factor_not_found"

    def test_delete_cross_tenant_returns_404(self) -> None:
        """Factor owned by tenant_A is invisible to tenant_B -> 404."""
        app.dependency_overrides[get_current_user] = _auth_override(
            "data_steward", tenant_id=_TENANT_B, user_id=_USER_DS
        )
        app.dependency_overrides[get_db] = _db_for_delete(None)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.delete(_DELETE_URL)

        assert resp.status_code == 404


class TestDeleteAuth:
    """Authentication and authorisation failures for DELETE."""

    @pytest.mark.parametrize("role", ["auditor", "esg_manager"])
    def test_delete_unauth_role_returns_403(self, role: str) -> None:
        """auditor and esg_manager do not have factor_catalog:write -> 403."""
        factor = _make_factor_orm(is_published=False)
        app.dependency_overrides[get_current_user] = _auth_override(role)
        app.dependency_overrides[get_db] = _db_for_delete(factor)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.delete(_DELETE_URL)

        assert resp.status_code == 403

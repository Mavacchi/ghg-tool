"""Unit tests for extended admin user CRUD endpoints (#8).

Covers:
- PATCH /api/v1/users/{user_uuid}/active
- PATCH /api/v1/users/{user_uuid}/role
- POST  /api/v1/users/{user_uuid}/password-reset

All DB access is mocked; no live PostgreSQL instance required.
"""

from __future__ import annotations

import os
import uuid
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

_TENANT = str(uuid.uuid4())
_ESG1 = str(uuid.uuid4())   # primary admin (caller)
_ESG2 = str(uuid.uuid4())   # second admin (target for demotion/deactivation)
_DS = str(uuid.uuid4())     # editor
_AU = str(uuid.uuid4())     # viewer
_USER_TARGET = str(uuid.uuid4())  # generic target user (viewer role in DB)

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


def _make_row(**kwargs: Any) -> MagicMock:
    """Build a MagicMock that looks like a DB row from _fetch_user_in_tenant."""
    row = MagicMock()
    row.id = uuid.UUID(kwargs.get("id", _USER_TARGET))
    row.username = kwargs.get("username", "testuser")
    row.email = kwargs.get("email", "test@example.com")
    row.role_code = kwargs.get("role_code", "viewer")
    row.role_id = uuid.uuid4()
    row.is_active = kwargs.get("is_active", True)
    return row


def _make_role_row() -> MagicMock:
    """Build a MagicMock that looks like a ref.roles row."""
    row = MagicMock()
    row.id = uuid.uuid4()
    return row


def _db_for_active_patch(
    target_row: MagicMock | None,
    active_manager_count: int = 2,
) -> Any:
    """DB override for PATCH /active tests.

    execute() is called in this order:
      1. _fetch_user_in_tenant SELECT
      2. _count_active_admins SELECT (only when needed for guard)
      3. UPDATE
    """
    async def _gen() -> Any:
        session = AsyncMock()
        session.flush = AsyncMock(return_value=None)
        session.add = MagicMock(return_value=None)

        # Result 1: SELECT for _fetch_user_in_tenant
        fetch_result = MagicMock()
        fetch_result.fetchone = MagicMock(return_value=target_row)

        # Result 2: SELECT count for _count_active_admins
        count_result = MagicMock()
        count_result.fetchone = MagicMock(return_value=(active_manager_count,))

        # Result 3: UPDATE (rowcount not used in PATCH /active)
        update_result = MagicMock()

        session.execute = AsyncMock(
            side_effect=[fetch_result, count_result, update_result]
        )
        yield session

    return _gen


def _db_for_role_patch(
    target_row: MagicMock | None,
    active_manager_count: int = 2,
) -> Any:
    """DB override for PATCH /role tests.

    execute() calls:
      1. _fetch_user_in_tenant SELECT
      2. _count_active_admins SELECT (guard; only for admin demotion)
      3. SELECT ref.roles for new role_id
      4. UPDATE
    """
    async def _gen() -> Any:
        session = AsyncMock()
        session.flush = AsyncMock(return_value=None)
        session.add = MagicMock(return_value=None)

        fetch_result = MagicMock()
        fetch_result.fetchone = MagicMock(return_value=target_row)

        count_result = MagicMock()
        count_result.fetchone = MagicMock(return_value=(active_manager_count,))

        role_result = MagicMock()
        role_result.fetchone = MagicMock(return_value=_make_role_row())

        update_result = MagicMock()

        session.execute = AsyncMock(
            side_effect=[fetch_result, count_result, role_result, update_result]
        )
        yield session

    return _gen


def _db_for_role_patch_no_count(target_row: MagicMock | None) -> Any:
    """DB override for role change that does NOT trigger the last-admin count.

    Used when the target is NOT an admin (so count check is skipped).
    execute() calls: fetch + role_select + update.
    """
    async def _gen() -> Any:
        session = AsyncMock()
        session.flush = AsyncMock(return_value=None)
        session.add = MagicMock(return_value=None)

        fetch_result = MagicMock()
        fetch_result.fetchone = MagicMock(return_value=target_row)

        role_result = MagicMock()
        role_result.fetchone = MagicMock(return_value=_make_role_row())

        update_result = MagicMock()

        session.execute = AsyncMock(
            side_effect=[fetch_result, role_result, update_result]
        )
        yield session

    return _gen


def _db_for_password_reset(target_row: MagicMock | None) -> Any:
    """DB override for POST /password-reset tests."""
    async def _gen() -> Any:
        session = AsyncMock()
        session.flush = AsyncMock(return_value=None)
        session.add = MagicMock(return_value=None)

        fetch_result = MagicMock()
        fetch_result.fetchone = MagicMock(return_value=target_row)

        update_result = MagicMock()

        # S-014: password reset also revokes active auth.sessions rows; the
        # router does a third UPDATE, so the mock needs a third Result with
        # rowcount=0 (no sessions to revoke in the unit fixture).
        revoke_result = MagicMock()
        revoke_result.rowcount = 0

        session.execute = AsyncMock(
            side_effect=[fetch_result, update_result, revoke_result]
        )
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
# PATCH /active tests
# ---------------------------------------------------------------------------


class TestPatchUserActive:
    """Tests for PATCH /api/v1/users/{user_uuid}/active."""

    def _url(self, user_id: str = _USER_TARGET) -> str:
        return f"/api/v1/users/{user_id}/active"

    def test_happy_path_deactivate_returns_200_is_active_false(self) -> None:
        """Deactivating a non-admin, non-self user -> 200 + is_active False."""
        target = _make_row(
            id=_USER_TARGET, role_code="viewer", is_active=True
        )
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        # Only two execute calls needed: fetch + update (no count needed for non-esg)
        async def _gen() -> Any:
            session = AsyncMock()
            session.flush = AsyncMock(return_value=None)
            session.add = MagicMock(return_value=None)
            fetch_result = MagicMock()
            fetch_result.fetchone = MagicMock(return_value=target)
            update_result = MagicMock()
            revoke_result = MagicMock()
            revoke_result.rowcount = 0  # S-014 session-revoke step
            session.execute = AsyncMock(
                side_effect=[fetch_result, update_result, revoke_result]
            )
            yield session

        app.dependency_overrides[get_db] = _gen

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(self._url(), json={"is_active": False})

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_active"] is False
        assert data["role_code"] == "viewer"

    def test_422_self_deactivation_forbidden(self) -> None:
        """Caller deactivating themselves -> 422 self_deactivation_forbidden."""
        target = _make_row(id=_ESG1, role_code="admin", is_active=True)
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        async def _gen() -> Any:
            session = AsyncMock()
            session.flush = AsyncMock(return_value=None)
            session.add = MagicMock(return_value=None)
            fetch_result = MagicMock()
            fetch_result.fetchone = MagicMock(return_value=target)
            session.execute = AsyncMock(return_value=fetch_result)
            yield session

        app.dependency_overrides[get_db] = _gen

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(self._url(_ESG1), json={"is_active": False})

        assert resp.status_code == 422
        assert resp.json()["detail"]["error_code"] == "self_deactivation_forbidden"

    def test_422_last_admin_deactivation_blocked(self) -> None:
        """Cannot deactivate the last active admin -> 422 last_admin."""
        target = _make_row(id=_ESG2, role_code="admin", is_active=True)
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        # active_manager_count = 1 -> triggers the guard
        app.dependency_overrides[get_db] = _db_for_active_patch(
            target, active_manager_count=1
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(self._url(_ESG2), json={"is_active": False})

        assert resp.status_code == 422
        assert resp.json()["detail"]["error_code"] == "last_admin"

    def test_404_user_not_found(self) -> None:
        """Unknown user UUID -> 404."""
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        async def _gen() -> Any:
            session = AsyncMock()
            fetch_result = MagicMock()
            fetch_result.fetchone = MagicMock(return_value=None)
            session.execute = AsyncMock(return_value=fetch_result)
            yield session

        app.dependency_overrides[get_db] = _gen

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(
                self._url(str(uuid.uuid4())), json={"is_active": False}
            )

        assert resp.status_code == 404

    def test_401_unauthenticated(self) -> None:
        """No token -> 401."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(self._url(), json={"is_active": False})
        assert resp.status_code == 401

    def test_403_data_steward_forbidden(self) -> None:
        """editor cannot change active state -> 403."""
        app.dependency_overrides[get_current_user] = _auth("editor", _DS)
        app.dependency_overrides[get_db] = _db_for_active_patch(None)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(self._url(), json={"is_active": True})
        assert resp.status_code == 403

    def test_403_auditor_forbidden(self) -> None:
        """viewer cannot change active state -> 403."""
        app.dependency_overrides[get_current_user] = _auth("viewer", _AU)
        app.dependency_overrides[get_db] = _db_for_active_patch(None)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(self._url(), json={"is_active": True})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PATCH /role tests
# ---------------------------------------------------------------------------


class TestPatchUserRole:
    """Tests for PATCH /api/v1/users/{user_uuid}/role."""

    def _url(self, user_id: str = _USER_TARGET) -> str:
        return f"/api/v1/users/{user_id}/role"

    def test_happy_path_role_change_auditor_to_data_steward_200(self) -> None:
        """Change viewer -> editor -> 200 with updated role_code."""
        target = _make_row(id=_USER_TARGET, role_code="viewer", is_active=True)
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        app.dependency_overrides[get_db] = _db_for_role_patch_no_count(target)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(self._url(), json={"role_code": "editor"})

        assert resp.status_code == 200
        assert resp.json()["role_code"] == "editor"

    def test_422_last_admin_demotion_blocked(self) -> None:
        """Cannot demote the last active admin -> 422 last_admin."""
        target = _make_row(id=_ESG2, role_code="admin", is_active=True)
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        # Only 1 active admin remaining
        app.dependency_overrides[get_db] = _db_for_role_patch(
            target, active_manager_count=1
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(self._url(_ESG2), json={"role_code": "editor"})

        assert resp.status_code == 422
        assert resp.json()["detail"]["error_code"] == "last_admin"

    def test_401_unauthenticated(self) -> None:
        """No token -> 401."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(self._url(), json={"role_code": "editor"})
        assert resp.status_code == 401

    def test_403_data_steward_forbidden(self) -> None:
        """editor cannot change roles -> 403."""
        app.dependency_overrides[get_current_user] = _auth("editor", _DS)
        app.dependency_overrides[get_db] = _db_for_role_patch(None)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(self._url(), json={"role_code": "viewer"})
        assert resp.status_code == 403

    def test_403_auditor_forbidden(self) -> None:
        """viewer cannot change roles -> 403."""
        app.dependency_overrides[get_current_user] = _auth("viewer", _AU)
        app.dependency_overrides[get_db] = _db_for_role_patch(None)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(self._url(), json={"role_code": "viewer"})
        assert resp.status_code == 403

    def test_422_invalid_role_code_rejected_by_pydantic(self) -> None:
        """Unknown role_code -> 422 from Pydantic before handler runs."""
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        app.dependency_overrides[get_db] = _db_for_role_patch_no_count(None)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.patch(self._url(), json={"role_code": "superadmin"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /password-reset tests
# ---------------------------------------------------------------------------


class TestPasswordReset:
    """Tests for POST /api/v1/users/{user_uuid}/password-reset."""

    def _url(self, user_id: str = _USER_TARGET) -> str:
        return f"/api/v1/users/{user_id}/password-reset"

    def test_happy_path_explicit_password_returned_in_response(self) -> None:
        """Explicit new_password -> 200, returned verbatim in response."""
        target = _make_row(id=_USER_TARGET, role_code="viewer", is_active=True)
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        app.dependency_overrides[get_db] = _db_for_password_reset(target)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(self._url(), json={"new_password": "N3wS3cur3Pass!"})

        assert resp.status_code == 200
        assert resp.json()["new_password"] == "N3wS3cur3Pass!"

    def test_happy_path_explicit_password_audit_row_excludes_plaintext(self) -> None:
        """Audit row after_state must NOT contain new_password or password_hash."""
        target = _make_row(id=_USER_TARGET, role_code="viewer", is_active=True)
        captured_adds: list[Any] = []

        async def _gen() -> Any:
            session = AsyncMock()
            session.flush = AsyncMock(return_value=None)

            def _capture_add(obj: Any) -> None:
                captured_adds.append(obj)

            session.add = MagicMock(side_effect=_capture_add)

            fetch_result = MagicMock()
            fetch_result.fetchone = MagicMock(return_value=target)
            update_result = MagicMock()
            revoke_result = MagicMock()
            revoke_result.rowcount = 0  # S-014 session-revoke step
            session.execute = AsyncMock(
                side_effect=[fetch_result, update_result, revoke_result]
            )
            yield session

        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        app.dependency_overrides[get_db] = _gen

        with TestClient(app, raise_server_exceptions=False) as client:
            client.post(self._url(), json={"new_password": "N3wS3cur3Pass!"})

        from ghg_tool.infrastructure.db.models.audit_log import AuditLog
        audit_rows = [a for a in captured_adds if isinstance(a, AuditLog)]
        assert len(audit_rows) == 1
        after = audit_rows[0].after_state or {}
        assert "new_password" not in after
        assert "password_hash" not in after
        assert "reset_at" in after

    def test_happy_path_no_body_generates_random_password(self) -> None:
        """No body -> server generates 16-char password; returned in response."""
        target = _make_row(id=_USER_TARGET, role_code="viewer", is_active=True)
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        app.dependency_overrides[get_db] = _db_for_password_reset(target)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(self._url())

        assert resp.status_code == 200
        pwd = resp.json()["new_password"]
        assert isinstance(pwd, str)
        assert len(pwd) == 16

    def test_happy_path_null_new_password_generates_random(self) -> None:
        """Explicit null new_password -> server generates 16-char password."""
        target = _make_row(id=_USER_TARGET, role_code="viewer", is_active=True)
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        app.dependency_overrides[get_db] = _db_for_password_reset(target)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(self._url(), json={"new_password": None})

        assert resp.status_code == 200
        assert len(resp.json()["new_password"]) == 16

    def test_401_unauthenticated(self) -> None:
        """No token -> 401."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(self._url(), json={"new_password": "SomePass123!"})
        assert resp.status_code == 401

    def test_403_data_steward_forbidden(self) -> None:
        """editor cannot reset passwords -> 403."""
        app.dependency_overrides[get_current_user] = _auth("editor", _DS)
        app.dependency_overrides[get_db] = _db_for_password_reset(None)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(self._url(), json={"new_password": "SomePass123!"})
        assert resp.status_code == 403

    def test_403_auditor_forbidden(self) -> None:
        """viewer cannot reset passwords -> 403."""
        app.dependency_overrides[get_current_user] = _auth("viewer", _AU)
        app.dependency_overrides[get_db] = _db_for_password_reset(None)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(self._url(), json={"new_password": "SomePass123!"})
        assert resp.status_code == 403

    def test_422_password_too_short(self) -> None:
        """new_password shorter than 8 chars -> 422 from Pydantic."""
        app.dependency_overrides[get_current_user] = _auth("admin", _ESG1)
        app.dependency_overrides[get_db] = _db_for_password_reset(None)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(self._url(), json={"new_password": "short"})
        assert resp.status_code == 422

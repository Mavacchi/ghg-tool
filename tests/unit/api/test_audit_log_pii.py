"""Unit tests for C-012: audit_log.after_state must not contain PII (username/email).

When ``POST /api/v1/users`` creates a user, the ``AuditLog`` row written in the same
transaction must store only UUID-based identifiers in ``after_state``, not the raw
``username`` or ``email`` strings.

All DB operations are mocked; no live PostgreSQL instance required.
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
from ghg_tool.infrastructure.db.models.audit_log import AuditLog

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TENANT = str(uuid.uuid4())
_ESG_USER = str(uuid.uuid4())
_NEW_USER_ID = uuid.uuid4()
_ROLE_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_esg_user() -> CurrentUser:
    return CurrentUser(
        sub=_ESG_USER,
        role="admin",  # type: ignore[arg-type]
        tenant_id=_TENANT,
        jti=str(uuid.uuid4()),
    )


def _auth_override() -> Any:
    user = _make_esg_user()

    async def _dep() -> CurrentUser:
        return user

    return _dep


def _db_for_create_user(captured_adds: list[Any]) -> Any:
    """DB mock for POST /api/v1/users.

    execute() is called in this order:
      1. SELECT ref.roles WHERE role_code = :rc
      2. INSERT INTO ref.users
    session.add() is called once for the AuditLog row.
    """

    async def _gen() -> Any:
        session = AsyncMock()
        session.flush = AsyncMock(return_value=None)

        def _capture_add(obj: Any) -> None:
            captured_adds.append(obj)

        session.add = MagicMock(side_effect=_capture_add)

        # Result 1: SELECT ref.roles
        role_row = MagicMock()
        role_row.id = _ROLE_ID
        role_result = MagicMock()
        role_result.fetchone = MagicMock(return_value=role_row)

        # Result 2: INSERT INTO ref.users (no returned value needed)
        insert_result = MagicMock()

        session.execute = AsyncMock(side_effect=[role_result, insert_result])
        yield session

    return _gen


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAuditLogAfterStatePII:
    """C-012: audit_log.after_state for user_created must not contain PII."""

    def test_after_state_has_no_username_or_email(self) -> None:
        """Create a user and assert the audit_log row has no username/email."""
        captured_adds: list[Any] = []

        app.dependency_overrides[get_current_user] = _auth_override()
        app.dependency_overrides[get_db] = _db_for_create_user(captured_adds)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/users",
                json={
                    "username": "alice.smith",
                    "email": "alice.smith@gresmalt.it",
                    "password": "S3curePass!",
                    "role_code": "editor",
                },
            )

        app.dependency_overrides.clear()

        assert resp.status_code == 201, resp.text

        # Locate the AuditLog row in the captured session.add() calls.
        audit_rows = [obj for obj in captured_adds if isinstance(obj, AuditLog)]
        assert len(audit_rows) == 1, (
            f"Expected exactly 1 AuditLog row, got: {len(audit_rows)}"
        )

        after = audit_rows[0].after_state or {}

        # PII fields that MUST NOT appear (C-012).
        assert "username" not in after, (
            f"'username' found in after_state: {after}"
        )
        assert "email" not in after, (
            f"'email' found in after_state: {after}"
        )

        # Required UUID-only fields MUST be present.
        assert "user_id" in after, f"'user_id' missing from after_state: {after}"
        assert "tenant_id" in after, f"'tenant_id' missing from after_state: {after}"
        assert "role_id" in after, f"'role_id' missing from after_state: {after}"
        assert "is_active" in after, f"'is_active' missing from after_state: {after}"

        # user_id must be a valid UUID string.
        uuid.UUID(after["user_id"])  # raises ValueError if not a valid UUID

        # is_active must be True on creation.
        assert after["is_active"] is True

    def test_after_state_action_is_user_created(self) -> None:
        """The AuditLog row action must be 'user_created'."""
        captured_adds: list[Any] = []

        app.dependency_overrides[get_current_user] = _auth_override()
        app.dependency_overrides[get_db] = _db_for_create_user(captured_adds)

        with TestClient(app, raise_server_exceptions=False) as client:
            client.post(
                "/api/v1/users",
                json={
                    "username": "bob.jones",
                    "email": "bob@gresmalt.it",
                    "password": "P@ssword123",
                    "role_code": "viewer",
                },
            )

        app.dependency_overrides.clear()

        audit_rows = [obj for obj in captured_adds if isinstance(obj, AuditLog)]
        assert len(audit_rows) == 1
        assert audit_rows[0].action == "user_created"

    def test_after_state_values_are_valid_uuids(self) -> None:
        """user_id, tenant_id, and role_id in after_state must be UUID strings."""
        captured_adds: list[Any] = []

        app.dependency_overrides[get_current_user] = _auth_override()
        app.dependency_overrides[get_db] = _db_for_create_user(captured_adds)

        with TestClient(app, raise_server_exceptions=False) as client:
            client.post(
                "/api/v1/users",
                json={
                    "username": "charlie.d",
                    "email": "charlie@gresmalt.it",
                    "password": "AnotherPass1!",
                    "role_code": "admin",
                },
            )

        app.dependency_overrides.clear()

        audit_rows = [obj for obj in captured_adds if isinstance(obj, AuditLog)]
        assert audit_rows, "No AuditLog row captured"
        after = audit_rows[0].after_state or {}

        # All UUID fields must parse as valid UUIDs.
        for field in ("user_id", "tenant_id", "role_id"):
            try:
                uuid.UUID(after[field])
            except (KeyError, ValueError) as exc:
                pytest.fail(
                    f"after_state['{field}'] is not a valid UUID: "
                    f"{after.get(field)!r} ({exc})"
                )

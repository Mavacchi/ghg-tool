"""Unit tests for JWT auto-provisioning of ref.users rows (Wave4 Task B).

Tests verify the ``get_or_provision_user`` function behaviour:
  1. New user from JWT → auto-provisioned in DB.
  2. Existing user → no provisioning (idempotent fast-path).
  3. Provisioning is idempotent under concurrent calls (ON CONFLICT DO NOTHING).
  4. Default role for auto-provisioned users is viewer.
  5. Username is extracted from ``preferred_username`` claim when present.

All DB interactions are mocked — no real PostgreSQL connection required.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import MagicMock

from ghg_tool.api.dependencies.auth import get_or_provision_user

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_TENANT_ID = str(uuid.uuid4())
_TEST_USER_ID = str(uuid.uuid4())
_VIEWER_ROLE_ID = str(uuid.uuid4())


def _make_session(
    *,
    user_exists: bool = False,
    viewer_role_id: str | None = None,
) -> MagicMock:
    """Build a mock async session for auto-provisioning tests.

    The mock tracks ``execute`` calls so tests can inspect the SQL
    statements passed without requiring a real database.

    Args:
        user_exists: When True, the first SELECT returns a row (user found).
            When False, returns None (user not present).
        viewer_role_id: The UUID to return for the viewer role lookup.
            When None the lookup returns None, simulating a missing role.

    Returns:
        A configured ``MagicMock`` with an async ``execute`` method.
    """
    execute_calls: list[tuple[Any, ...]] = []
    call_index = [0]

    def _select_user_result(exists: bool) -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = _TEST_USER_ID if exists else None
        return result

    def _select_role_result(role_id: str | None) -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = role_id
        return result

    # A plain noop result for INSERT statements.
    noop_result = MagicMock()

    async def _execute(stmt: Any, params: Any = None) -> MagicMock:
        execute_calls.append((stmt, params))
        idx = call_index[0]
        call_index[0] += 1
        # First call: SELECT from ref.users
        if idx == 0:
            return _select_user_result(user_exists)
        # Second call (only reached when user is absent): SELECT viewer role
        if idx == 1:
            return _select_role_result(viewer_role_id)
        # Subsequent calls: INSERT statement
        return noop_result

    session = MagicMock()
    session.execute = _execute
    session._execute_calls = execute_calls  # expose for assertions
    return session


# ---------------------------------------------------------------------------
# Test 1: New user JWT → auto-provisioned in DB
# ---------------------------------------------------------------------------

def test_new_user_jwt_is_auto_provisioned() -> None:
    """A JWT-verified user absent from ref.users triggers an INSERT.

    After calling ``get_or_provision_user`` with a JWT payload whose ``sub``
    is not found in the DB, the session must have received exactly three
    execute calls: SELECT user, SELECT viewer role, INSERT user.
    """
    session = _make_session(user_exists=False, viewer_role_id=_VIEWER_ROLE_ID)
    jwt_payload = {
        "sub": _TEST_USER_ID,
        "preferred_username": "alice",
        "email": "alice@example.com",
    }

    asyncio.run(
        get_or_provision_user(session, jwt_payload, tenant_id=_TEST_TENANT_ID)
    )

    calls = session._execute_calls
    assert len(calls) == 3, (
        f"Expected 3 execute calls (SELECT user, SELECT role, INSERT), got {len(calls)}"
    )
    # Third call is the INSERT — verify it contains the user_id
    insert_params = calls[2][1]
    assert insert_params is not None
    assert insert_params["id"] == _TEST_USER_ID
    assert insert_params["tenant_id"] == _TEST_TENANT_ID


# ---------------------------------------------------------------------------
# Test 2: Existing user → no provisioning
# ---------------------------------------------------------------------------

def test_existing_user_skips_provisioning() -> None:
    """A user already in ref.users must not trigger any INSERT.

    When the SELECT returns the user row, ``get_or_provision_user`` must
    return immediately — no role lookup and no INSERT should occur.
    """
    session = _make_session(user_exists=True)
    jwt_payload = {"sub": _TEST_USER_ID}

    asyncio.run(
        get_or_provision_user(session, jwt_payload, tenant_id=_TEST_TENANT_ID)
    )

    calls = session._execute_calls
    assert len(calls) == 1, (
        f"Expected only 1 execute call (SELECT user exists check), got {len(calls)}"
    )


# ---------------------------------------------------------------------------
# Test 3: Provisioning is idempotent (ON CONFLICT DO NOTHING)
# ---------------------------------------------------------------------------

def test_provisioning_idempotent_on_concurrent_calls() -> None:
    """Two concurrent calls for the same new user must produce exactly one INSERT.

    We simulate concurrency by calling ``get_or_provision_user`` twice in
    sequence with a session that always reports the user as absent (simulating
    the race window before the first INSERT commits).  Both calls attempt an
    INSERT; the DB handles the conflict with ON CONFLICT DO NOTHING.

    We verify that the INSERT SQL text contains "ON CONFLICT" so that the
    idempotency contract is preserved at the SQL layer.
    """
    # Both calls will see user_exists=False (race condition simulation)
    session_1 = _make_session(user_exists=False, viewer_role_id=_VIEWER_ROLE_ID)
    session_2 = _make_session(user_exists=False, viewer_role_id=_VIEWER_ROLE_ID)

    jwt_payload = {"sub": _TEST_USER_ID}

    asyncio.run(
        get_or_provision_user(session_1, jwt_payload, tenant_id=_TEST_TENANT_ID)
    )
    asyncio.run(
        get_or_provision_user(session_2, jwt_payload, tenant_id=_TEST_TENANT_ID)
    )

    # Both sessions issued an INSERT — verify the ON CONFLICT clause is present
    # in the SQL text to ensure idempotency is enforced at the DB layer.
    for session in (session_1, session_2):
        calls = session._execute_calls
        assert len(calls) == 3, f"Expected 3 calls, got {len(calls)}"
        insert_stmt = calls[2][0]  # The third call is the INSERT
        stmt_text = str(insert_stmt).lower()
        assert "on conflict" in stmt_text, (
            f"INSERT statement must contain ON CONFLICT for idempotency; "
            f"got: {stmt_text[:200]}"
        )


# ---------------------------------------------------------------------------
# Test 4: Default role = viewer
# ---------------------------------------------------------------------------

def test_auto_provisioned_user_gets_viewer_role() -> None:
    """Auto-provisioned users must receive the viewer role (most restrictive).

    The INSERT params must reference the viewer role UUID returned by the
    role lookup, not any other role.
    """
    session = _make_session(user_exists=False, viewer_role_id=_VIEWER_ROLE_ID)
    jwt_payload = {"sub": _TEST_USER_ID}

    asyncio.run(
        get_or_provision_user(session, jwt_payload, tenant_id=_TEST_TENANT_ID)
    )

    calls = session._execute_calls
    insert_params = calls[2][1]
    assert insert_params is not None
    assert insert_params["role_id"] == _VIEWER_ROLE_ID, (
        f"Expected viewer role_id={_VIEWER_ROLE_ID}; got {insert_params.get('role_id')}"
    )


# ---------------------------------------------------------------------------
# Test 5: Username extracted from preferred_username claim
# ---------------------------------------------------------------------------

def test_username_extracted_from_preferred_username_claim() -> None:
    """Username is taken from ``preferred_username`` JWT claim when present.

    Fallback to ``auto_<sub[:8]>`` applies only when the claim is absent.
    """
    custom_username = "maria.rossi"
    session = _make_session(user_exists=False, viewer_role_id=_VIEWER_ROLE_ID)
    jwt_payload = {
        "sub": _TEST_USER_ID,
        "preferred_username": custom_username,
        "email": "maria@example.com",
    }

    asyncio.run(
        get_or_provision_user(session, jwt_payload, tenant_id=_TEST_TENANT_ID)
    )

    calls = session._execute_calls
    insert_params = calls[2][1]
    assert insert_params is not None
    assert insert_params["username"] == custom_username, (
        f"Expected username={custom_username!r}; got {insert_params.get('username')!r}"
    )
    assert insert_params["email"] == "maria@example.com"


# ---------------------------------------------------------------------------
# Extra: fallback username when preferred_username is absent
# ---------------------------------------------------------------------------

def test_username_fallback_when_preferred_username_absent() -> None:
    """When ``preferred_username`` is absent, username is ``auto_<sub[:8]>``."""
    session = _make_session(user_exists=False, viewer_role_id=_VIEWER_ROLE_ID)
    jwt_payload = {
        "sub": _TEST_USER_ID,
        # preferred_username deliberately omitted
    }

    asyncio.run(
        get_or_provision_user(session, jwt_payload, tenant_id=_TEST_TENANT_ID)
    )

    calls = session._execute_calls
    insert_params = calls[2][1]
    assert insert_params is not None
    expected_username = f"auto_{_TEST_USER_ID[:8]}"
    assert insert_params["username"] == expected_username, (
        f"Expected fallback username={expected_username!r}; "
        f"got {insert_params.get('username')!r}"
    )
    expected_email = f"auto_{_TEST_USER_ID[:8]}@unknown.local"
    assert insert_params["email"] == expected_email, (
        f"Expected fallback email={expected_email!r}; "
        f"got {insert_params.get('email')!r}"
    )

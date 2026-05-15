"""API integration test fixtures.

Provides the ``seeded_auth_session`` fixture that satisfies the
``SessionCheckMiddleware`` contract: for every JWT minted in a test, a
corresponding row in ``auth.sessions`` is inserted into the test database so
that the middleware's ``SELECT … WHERE jti = :jti`` lookup succeeds.

Design notes
------------
* **Function-scoped** — each test method calls token helpers that mint a fresh
  JWT with a new ``jti``.  Function scope guarantees that each test starts with
  a clean ``auth.sessions`` state and that teardown DELETEs only the rows
  created by that test.
* **Real INSERT** — no mocking.  The fixture opens a direct asyncpg connection
  via the session-scoped ``db_engine`` from ``tests/integration/conftest.py``.
* **FK chain** — ``auth.sessions.user_id`` references ``ref.users.id``.  The
  fixture inserts a throw-away ``ref.users`` row using the same UUID that will
  be embedded as ``sub`` in the JWT; it deletes that row on teardown.
* **RLS bypass** — the test connection is a superuser (``ghg_test`` / owner),
  which bypasses ``FORCE ROW LEVEL SECURITY`` on all tables.  The fixture sets
  ``app.tenant_id`` and ``app.role_code`` GUCs on the connection so that RLS
  policies evaluate correctly for the insert's ``WITH CHECK``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Literal

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ghg_tool.infrastructure.security.jwt import (
    create_access_token,
    get_unverified_claims,
)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

_Role = Literal["editor", "admin", "viewer", "admin"]


# ---------------------------------------------------------------------------
# seeded_auth_session
# ---------------------------------------------------------------------------


class SessionMinter:
    """Helper returned by ``seeded_auth_session``; mints JWTs and seeds rows.

    Each call to :meth:`mint` creates one ``ref.users`` row + one
    ``auth.sessions`` row in the test database and returns the signed JWT
    string.  All inserted rows are tracked and deleted in bulk during fixture
    teardown.
    """

    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id
        # Track inserted IDs for teardown
        self._user_ids: list[str] = []
        self._session_jtis: list[str] = []

    async def mint(
        self,
        role: _Role = "editor",
        *,
        jwt_tenant_id_override: str | None = None,
    ) -> str:
        """Mint a signed JWT for *role* and seed the matching auth.sessions row.

        The ``auth.sessions`` row is always inserted under ``self._tenant_id``
        (the fixture's real seeded tenant) so that the FK to ``ref.tenants``
        and ``ref.users`` is satisfied.

        When *jwt_tenant_id_override* is supplied the JWT's ``tenant_id`` claim
        is set to that value instead of ``self._tenant_id``.  This is used by
        cross-tenant RLS tests that need a token whose claim carries an
        unrecognised tenant while still passing the middleware's ``jti`` lookup
        (which checks only ``auth.sessions.jti``, not the claim's tenant).

        Args:
            role: RBAC role to embed in the JWT.
            jwt_tenant_id_override: Optional tenant UUID to embed in the JWT
                ``tenant_id`` claim instead of the real seeded tenant.

        Returns:
            Signed JWT string ready for use in ``Authorization: Bearer`` headers.
        """
        user_id = str(uuid.uuid4())
        jwt_tenant_id = jwt_tenant_id_override or self._tenant_id

        # We need a role_id FK. Look it up by role_code.
        role_row = await self._session.execute(
            text(
                "SELECT id::text FROM ref.roles "
                "WHERE role_code = :role LIMIT 1"
            ),
            {"role": role},
        )
        role_id = role_row.scalar_one_or_none()
        if role_id is None:
            # Fall back to any role if this code is not seeded
            role_row_any = await self._session.execute(
                text("SELECT id::text FROM ref.roles LIMIT 1")
            )
            role_id = role_row_any.scalar_one()

        # Insert a minimal ref.users row (under the real tenant) so the
        # auth.sessions FK is satisfied.  The superuser connection bypasses
        # FORCE RLS; GUCs are already set for belt-and-suspenders compliance.
        suffix = user_id[:8]
        await self._session.execute(
            text(
                "INSERT INTO ref.users "
                "(id, tenant_id, username, email, password_hash, role_id) "
                "VALUES ("
                "  CAST(:uid AS uuid), CAST(:tid AS uuid), "
                "  :uname, :email, :phash, CAST(:rid AS uuid)"
                ")"
            ),
            {
                "uid": user_id,
                "tid": self._tenant_id,  # always the real tenant for FK validity
                "uname": f"test_user_{suffix}",
                "email": f"test_{suffix}@integration.test",
                "phash": "$2b$12$test_placeholder_hash_not_real",
                "rid": role_id,
            },
        )
        self._user_ids.append(user_id)

        # Mint the JWT; tenant_id claim may differ from the session row's tenant.
        token = create_access_token(
            sub=user_id,
            role=role,
            tenant_id=jwt_tenant_id,
        )

        # Decode unverified to extract the jti without a round-trip.
        claims = get_unverified_claims(token)
        jti: str = str(claims["jti"])

        # Insert the auth.sessions row the middleware will look up.
        # The session is stored under the real tenant (FK constraint).
        await self._session.execute(
            text(
                "INSERT INTO auth.sessions "
                "(id, user_id, tenant_id, jti, ip_address, user_agent) "
                "VALUES ("
                "  gen_random_uuid(), "
                "  CAST(:uid AS uuid), "
                "  CAST(:tid AS uuid), "
                "  :jti, "
                "  CAST('127.0.0.1' AS inet), "
                "  'integration-test-agent'"
                ")"
            ),
            {
                "uid": user_id,
                "tid": self._tenant_id,  # always the real tenant for FK validity
                "jti": jti,
            },
        )
        self._session_jtis.append(jti)

        # Commit so the middleware's independent DB connection sees the rows.
        await self._session.commit()

        return token

    async def _cleanup(self) -> None:
        """DELETE all rows inserted by this minter."""
        if self._session_jtis:
            await self._session.execute(
                text(
                    "DELETE FROM auth.sessions WHERE jti = ANY(CAST(:jtis AS VARCHAR[]))"
                ),
                {"jtis": self._session_jtis},
            )
        if self._user_ids:
            await self._session.execute(
                text(
                    "DELETE FROM ref.users WHERE id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": [f"{i}" for i in self._user_ids]},
            )
        await self._session.commit()


@pytest_asyncio.fixture()
async def seeded_auth_session(
    db_engine: AsyncEngine,
    tenant_id: str,
) -> AsyncIterator[SessionMinter]:
    """Yield a :class:`SessionMinter` that mints JWTs and seeds auth.sessions rows.

    Scope: **function** — each test gets its own set of session rows and its
    own teardown DELETE so that tests remain isolated even when they commit
    data (as some API integration tests must, to make rows visible to the
    middleware's independent DB connection).

    Usage in a test::

        async def test_something(self, seeded_auth_session, tenant_id):
            token = await seeded_auth_session.mint("editor")
            async with AsyncClient(app=fastapi_app, base_url="http://testserver") as c:
                resp = await c.post("/api/v1/emissions/", ...,
                                    headers={"Authorization": f"Bearer {token}"})

    The fixture sets the ``app.tenant_id`` and ``app.role_code`` session GUCs
    (transaction-local via ``set_config``) so that RLS ``WITH CHECK`` policies
    on ``ref.users`` and ``auth.sessions`` evaluate correctly on the superuser
    connection.
    """
    SessionLocal = async_sessionmaker(
        db_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with SessionLocal() as session:
        # Set RLS GUCs so that FORCE RLS WITH CHECK on ref.users and
        # auth.sessions does not block the superuser's own INSERTs when
        # the policies are evaluated in non-bypass mode (belt-and-suspenders:
        # the superuser technically bypasses FORCE RLS, but setting the GUC
        # keeps us consistent with the rest of the conftest pattern).
        await session.execute(
            text(
                "SELECT set_config('app.tenant_id', :tid, false), "
                "       set_config('app.role_code', 'editor', false)"
            ),
            {"tid": tenant_id},
        )
        minter = SessionMinter(session, tenant_id)
        try:
            yield minter
        finally:
            await minter._cleanup()

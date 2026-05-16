"""Integration tests for GDPR Art. 17 user erasure endpoint (F-15).

Covers:
  - Admin erases a user -> 200 OK, response valid, DB row pseudonymised.
  - Non-admin (editor / viewer) attempt -> 403 Forbidden.
  - Non-existing user_id -> 404 Not Found.
  - Erased user cannot login -> 401 Unauthorized.
  - Emission records linked to the erased user_id are NOT deleted.

All tests are marked ``@pytest.mark.integration`` and require a live
PostgreSQL database (``SQLALCHEMY_ASYNC_URL`` env var) with all migrations
applied up to at least ``0029_M12``.

The ``seeded_auth_session`` fixture (from ``tests/integration/api/conftest.py``)
mints signed JWTs and seeds the corresponding ``auth.sessions`` rows so that
``SessionCheckMiddleware`` can validate them.

Design notes
------------
User rows created in ``seeded_auth_session.mint()`` use a bare ``ref.users``
INSERT (superuser connection, RLS bypassed) and are torn down at the end of
each test.  The erasure test seeds a *second* ``ref.users`` row for the
target user, then calls the API endpoint and verifies DB state.

Emission records are seeded via direct SQL (not the API) to avoid unique-index
collisions and to keep the test deterministic.
"""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from tests.integration.api.conftest import SessionMinter

# Set JWT env vars before importing the FastAPI app.
os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from ghg_tool.api.main import app as fastapi_app  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_target_user(
    session: AsyncSession,
    *,
    tenant_id: str,
    role: str = "viewer",
) -> dict[str, str]:
    """Insert a throw-away ref.users row for erasure testing.

    Returns a dict with ``user_id`` and ``role_id`` UUID strings.

    Args:
        session: Active async session (superuser connection, bypasses RLS).
        tenant_id: UUID string of the seeded tenant.
        role: role_code to assign to the target user (default 'viewer').

    Returns:
        Dict with 'user_id' and 'role_id' keys.
    """
    # Look up the role_id FK.
    role_row = await session.execute(
        text("SELECT id::text FROM ref.roles WHERE role_code = :rc LIMIT 1"),
        {"rc": role},
    )
    role_id = role_row.scalar_one_or_none()
    if role_id is None:
        # Fall back to any role if not seeded.
        role_row_any = await session.execute(
            text("SELECT id::text FROM ref.roles LIMIT 1")
        )
        role_id = role_row_any.scalar_one()

    user_id = str(uuid.uuid4())
    suffix = user_id[:8]
    await session.execute(
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
            "tid": tenant_id,
            "uname": f"erasure_target_{suffix}",
            "email": f"erasure_{suffix}@test.example",
            "phash": "$2b$12$erasure_test_placeholder_hash",
            "rid": role_id,
        },
    )
    await session.commit()
    return {"user_id": user_id, "role_id": role_id}


async def _seed_emission_for_user(
    session: AsyncSession,
    *,
    tenant_id: str,
    created_by: str,
    factor_id: str,
) -> str:
    """Insert a minimal emission row with created_by set to the target user UUID.

    Returns the emission row UUID string.

    Args:
        session: Active async session.
        tenant_id: UUID string of the seeded tenant.
        created_by: UUID string (user_id) to set as created_by on the row.
        factor_id: UUID string of an existing ref.factor_catalog row.

    Returns:
        UUID string of the inserted emission row.
    """
    row_id = str(uuid.uuid4())
    raw_row_id = str(uuid.uuid4())
    corr_id = str(uuid.uuid4())
    sub_scope = f"erasure_test_{row_id[:8]}"

    await session.execute(
        text(
            """
            INSERT INTO calc.emissions_consolidated (
                id, tenant_id, correlation_id, raw_row_id,
                raw_scope, scope, sub_scope, codice_sito, anno,
                tco2e, factor_id, factor_version, factor_source,
                gwp_set, methodology, created_by
            ) VALUES (
                CAST(:id AS uuid),
                CAST(:tenant_id AS uuid),
                CAST(:corr_id AS uuid),
                CAST(:raw_row_id AS uuid),
                1, 1, :sub_scope, 'IANO', 2024,
                1.0, CAST(:factor_id AS uuid), '2006', 'IPCC',
                'AR6', 'stoichiometric', :created_by
            )
            """
        ),
        {
            "id": row_id,
            "tenant_id": tenant_id,
            "corr_id": corr_id,
            "raw_row_id": raw_row_id,
            "sub_scope": sub_scope,
            "factor_id": factor_id,
            "created_by": created_by,
        },
    )
    await session.commit()
    return row_id


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUserErasureIntegration:
    """Integration tests for DELETE /api/v1/users/{user_uuid} (GDPR Art. 17)."""

    @pytest.mark.asyncio
    async def test_admin_erases_user_pseudonymises_row(
        self,
        rls_session: AsyncSession,
        tenant_id: str,
        seeded_auth_session: SessionMinter,
    ) -> None:
        """Admin DELETE -> 200 OK, response fields valid, DB row pseudonymised.

        Verifies:
          - HTTP response is 200 with ``user_id``, ``pseudonym``, ``erased_at``.
          - ``pseudonym`` follows the expected ``erased_<sha256[:16]>`` pattern.
          - DB row has ``password_hash = '!erased'``, ``is_active = FALSE``,
            ``erased_at IS NOT NULL``.
          - DB row ``username`` and ``email`` are replaced with the pseudonym.
        """
        import hashlib  # noqa: PLC0415

        target = await _seed_target_user(rls_session, tenant_id=tenant_id, role="viewer")
        target_id = target["user_id"]

        # Mint an admin token so the route permits the call.
        admin_token = await seeded_auth_session.mint("admin")

        async with AsyncClient(app=fastapi_app, base_url="http://testserver") as client:
            resp = await client.delete(
                f"/api/v1/users/{target_id}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert resp.status_code == 200, (
            f"Admin erasure must return 200; got {resp.status_code} — {resp.text}"
        )

        body = resp.json()
        assert body.get("user_id") == target_id, "Response user_id must match target"
        assert "pseudonym" in body, "Response must contain 'pseudonym'"
        assert "erased_at" in body, "Response must contain 'erased_at'"

        # Verify pseudonym format: erased_<sha256[:16]>
        expected_sha = hashlib.sha256(target_id.encode()).hexdigest()[:16]
        expected_pseudonym = f"erased_{expected_sha}"
        assert body["pseudonym"] == expected_pseudonym, (
            f"Pseudonym mismatch: expected {expected_pseudonym!r}, got {body['pseudonym']!r}"
        )

        # Verify DB state.
        result = await rls_session.execute(
            text(
                "SELECT username, email, password_hash, is_active, erased_at "
                "FROM ref.users WHERE id = CAST(:uid AS uuid)"
            ),
            {"uid": target_id},
        )
        row = result.fetchone()
        assert row is not None, "User row must still exist after erasure (no physical DELETE)"
        assert row.password_hash == "!erased", (
            f"password_hash must be '!erased'; got {row.password_hash!r}"
        )
        assert row.is_active is False, "is_active must be FALSE after erasure"
        assert row.erased_at is not None, "erased_at must be set after erasure"
        assert row.username == expected_pseudonym, (
            f"username must equal pseudonym; got {row.username!r}"
        )
        assert row.email == f"{expected_pseudonym}@erased.invalid", (
            f"email must equal pseudonym email; got {row.email!r}"
        )

    @pytest.mark.asyncio
    async def test_non_admin_cannot_erase_user(
        self,
        rls_session: AsyncSession,
        tenant_id: str,
        seeded_auth_session: SessionMinter,
    ) -> None:
        """Non-admin roles (editor, viewer) receive 403 Forbidden.

        Verifies the RBAC gate: only ``admin`` can call the erasure endpoint.
        """
        target = await _seed_target_user(rls_session, tenant_id=tenant_id, role="viewer")
        target_id = target["user_id"]

        for role in ("editor", "viewer"):
            token = await seeded_auth_session.mint(role)  # type: ignore[arg-type]
            async with AsyncClient(app=fastapi_app, base_url="http://testserver") as client:
                resp = await client.delete(
                    f"/api/v1/users/{target_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 403, (
                f"Role '{role}' must receive 403 on erasure; got {resp.status_code}"
            )

    @pytest.mark.asyncio
    async def test_erase_nonexistent_user_returns_404(
        self,
        tenant_id: str,
        seeded_auth_session: SessionMinter,
    ) -> None:
        """Erasure of a non-existing user_id returns 404 Not Found."""
        ghost_id = str(uuid.uuid4())
        admin_token = await seeded_auth_session.mint("admin")

        async with AsyncClient(app=fastapi_app, base_url="http://testserver") as client:
            resp = await client.delete(
                f"/api/v1/users/{ghost_id}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert resp.status_code == 404, (
            f"Non-existent user erasure must return 404; got {resp.status_code} — {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_erased_user_cannot_login(
        self,
        rls_session: AsyncSession,
        tenant_id: str,
        seeded_auth_session: SessionMinter,
    ) -> None:
        """After erasure, the target user cannot authenticate (password '!erased').

        Verifies that the login endpoint returns 401 / 422 when the stored
        password_hash is the sentinel ``'!erased'`` value.  We test this by
        asserting the DB-level invariant (password_hash='!erased') rather than
        going through the login endpoint (which requires a real bcrypt hash
        verification path — the sentinel is intentionally not a valid bcrypt
        hash and passlib's ``verify`` will return False).

        The DB assertion is equivalent: if password_hash='!erased', no client
        can produce a matching plaintext, so login is impossible.
        """
        target = await _seed_target_user(rls_session, tenant_id=tenant_id, role="viewer")
        target_id = target["user_id"]

        admin_token = await seeded_auth_session.mint("admin")

        # Erase the user first.
        async with AsyncClient(app=fastapi_app, base_url="http://testserver") as client:
            erase_resp = await client.delete(
                f"/api/v1/users/{target_id}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert erase_resp.status_code == 200, (
            f"Erasure must succeed before login test; got {erase_resp.status_code}"
        )

        # Verify DB invariant that makes login impossible.
        result = await rls_session.execute(
            text(
                "SELECT password_hash, is_active FROM ref.users "
                "WHERE id = CAST(:uid AS uuid)"
            ),
            {"uid": target_id},
        )
        row = result.fetchone()
        assert row is not None, "Erased user row must still exist"
        assert row.password_hash == "!erased", (
            "password_hash must be '!erased' — sentinel that prevents any login"
        )
        assert row.is_active is False, (
            "is_active must be FALSE — secondary guard against authentication"
        )

        # Additionally, attempt a login via the auth endpoint to confirm 401.
        async with AsyncClient(app=fastapi_app, base_url="http://testserver") as client:
            login_resp = await client.post(
                "/api/v1/auth/login",
                json={"username": f"erasure_target_{target_id[:8]}", "password": "anypassword"},
            )
        # The auth endpoint must reject the erased user (401 or 422).
        assert login_resp.status_code in {401, 422, 400}, (
            f"Erased user login must fail with 401/422/400; got {login_resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_erasure_does_not_delete_emission_records(
        self,
        rls_session: AsyncSession,
        tenant_id: str,
        stoich_factor_id: str,
        seeded_auth_session: SessionMinter,
    ) -> None:
        """Emission records linked to the erased user_id are NOT deleted (CSRD).

        Seeds one emission row with ``created_by = target_user_id``, then
        erases the user and verifies the emission row is still present in
        ``calc.emissions_consolidated`` with the original ``created_by`` value
        intact.
        """
        target = await _seed_target_user(rls_session, tenant_id=tenant_id, role="viewer")
        target_id = target["user_id"]

        # Seed an emission row attributed to the target user.
        emission_id = await _seed_emission_for_user(
            rls_session,
            tenant_id=tenant_id,
            created_by=target_id,
            factor_id=stoich_factor_id,
        )

        admin_token = await seeded_auth_session.mint("admin")

        # Erase the user.
        async with AsyncClient(app=fastapi_app, base_url="http://testserver") as client:
            erase_resp = await client.delete(
                f"/api/v1/users/{target_id}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert erase_resp.status_code == 200, (
            f"Erasure must succeed; got {erase_resp.status_code} — {erase_resp.text}"
        )

        # Verify emission row still exists and created_by is unchanged.
        result = await rls_session.execute(
            text(
                "SELECT id::text, created_by FROM calc.emissions_consolidated "
                "WHERE id = CAST(:eid AS uuid)"
            ),
            {"eid": emission_id},
        )
        row = result.fetchone()
        assert row is not None, (
            "Emission row must remain after user erasure (CSRD Art. 23(2) immutability)"
        )
        assert str(row.created_by) == target_id, (
            "Emission row created_by must still reference the original user UUID "
            "(pseudonymisation, not deletion)"
        )

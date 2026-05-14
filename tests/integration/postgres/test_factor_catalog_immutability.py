"""Integration tests: factor_catalog post-publish immutability.

Verifies:
  - UPDATE on an unpublished (is_published=false) row succeeds (pre-publish
    edits are allowed -- a data steward may correct a draft factor before
    approving it).
  - Flipping is_published=true succeeds.
  - UPDATE after publishing raises (ops.deny_factor_mutation trigger, M0).
  - DELETE after publishing raises (same trigger).

The trigger name is trg_factor_immutable; the error message format from M0
is: 'Factor <factor_id>/<version> is published and immutable'.

ISAE 3000 relevance: published emission factors are used in certified
calculations.  Allowing post-publish mutations would mean the audit trail
could diverge from what the DB actually stores.  The trigger is the
database-level enforcement of that invariant.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helper: insert a draft factor row (is_published=false)
# ---------------------------------------------------------------------------


async def _insert_draft_factor(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    value: float = 0.33,
) -> tuple[str, str, str]:
    """Insert a draft factor row; return (row_uuid, factor_id_code, version).

    Draft factors are not subject to the immutability trigger; they can be
    edited freely until they are published.

    Args:
        engine: AsyncEngine for the test database.
        tenant_id: UUID string of the target tenant.
        value: Initial factor value.

    Returns:
        Tuple of (row UUID string, factor_id code, version string).
    """
    row_id = str(uuid.uuid4())
    factor_id_code = f"DRAFT_{row_id[:8].upper()}"
    version = "draft_v1"

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO ref.factor_catalog ("
                "  id, tenant_id, factor_id, version, substance, scope, "
                "  category, source, value, unit, gwp_set, valid_from, "
                "  is_published"
                ") VALUES ("
                "  CAST(:id AS uuid), CAST(:tid AS uuid), :fid, :ver, "
                "  'CO2', 1, 'combustion', 'IPCC', :val, 'kg/kWh', 'AR6', "
                "  '2024-01-01', FALSE"
                ")"
            ),
            {
                "id": row_id,
                "tid": tenant_id,
                "fid": factor_id_code,
                "ver": version,
                "val": value,
            },
        )
    return row_id, factor_id_code, version


# ---------------------------------------------------------------------------
# Test: UPDATE on draft row succeeds
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_draft_factor_succeeds(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """UPDATE on a draft (is_published=false) factor row succeeds.

    Pre-publish edits are the normal workflow: a data steward creates a
    draft factor, reviews it, and possibly corrects the value before
    calling the publish endpoint.  The trigger must not block this.
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    row_id, _, _ = await _insert_draft_factor(
        async_engine,
        tenant_id=seed.tenant_a,
        value=0.33,
    )

    # UPDATE the value while still a draft -- must succeed
    async with async_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE ref.factor_catalog SET value = 0.45 "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )

    # Verify the new value persisted
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT value FROM ref.factor_catalog WHERE id = CAST(:id AS uuid)"),
            {"id": row_id},
        )
        row = result.fetchone()

    assert row is not None
    assert abs(float(row[0]) - 0.45) < 1e-6, (
        f"Draft factor value must be 0.45 after UPDATE, got {row[0]}"
    )


# ---------------------------------------------------------------------------
# Test: publishing succeeds
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_factor_succeeds(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """Flipping is_published=true on a draft row succeeds.

    Publishing via UPDATE (setting is_published=true, published_at, published_by)
    must not raise, because the trigger only blocks mutations AFTER the row
    is already published (OLD.is_published = true in the trigger body).
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    row_id, _, _ = await _insert_draft_factor(
        async_engine,
        tenant_id=seed.tenant_a,
    )

    # Publish the factor -- must not raise
    async with async_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE ref.factor_catalog "
                "SET is_published = TRUE, "
                "    published_at = now(), "
                "    published_by = 'test_publish' "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )

    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT is_published, published_at, published_by "
                "FROM ref.factor_catalog WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )
        row = result.fetchone()

    assert row is not None
    assert row[0] is True, "is_published must be TRUE after publish UPDATE"
    assert row[1] is not None, "published_at must be set after publish"
    assert row[2] == "test_publish", f"published_by must be 'test_publish', got {row[2]}"


# ---------------------------------------------------------------------------
# Test: UPDATE after publishing raises
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_published_factor_raises(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """UPDATE on a published factor raises (ops.deny_factor_mutation trigger).

    After a factor is published, any further UPDATE must be rejected by
    trg_factor_immutable.  The error message from M0:
    'Factor <factor_id>/<version> is published and immutable'.
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    row_id, _, _ = await _insert_draft_factor(
        async_engine,
        tenant_id=seed.tenant_a,
    )

    # Publish first
    async with async_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE ref.factor_catalog "
                "SET is_published = TRUE, "
                "    published_at = now(), "
                "    published_by = 'test_publisher' "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )

    # Now attempt to mutate value -- must raise
    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)) as exc_info:
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE ref.factor_catalog SET value = 9999.0 "
                    "WHERE id = CAST(:id AS uuid)"
                ),
                {"id": row_id},
            )

    err_str = str(exc_info.value).lower()
    assert "immutable" in err_str or "published" in err_str or "p0001" in err_str, (
        f"Expected factor immutability trigger message, got: {exc_info.value}"
    )


# ---------------------------------------------------------------------------
# Test: DELETE after publishing raises
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_published_factor_raises(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """DELETE on a published factor raises (ops.deny_factor_mutation trigger).

    The trigger covers both UPDATE and DELETE (BEFORE UPDATE OR DELETE per
    M0 DDL).  Post-publish DELETE must raise regardless of column targeted.
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    row_id, _, _ = await _insert_draft_factor(
        async_engine,
        tenant_id=seed.tenant_a,
    )

    # Publish first
    async with async_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE ref.factor_catalog "
                "SET is_published = TRUE, "
                "    published_at = now(), "
                "    published_by = 'test_publisher' "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )

    # Attempt DELETE -- must raise
    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)) as exc_info:
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM ref.factor_catalog WHERE id = CAST(:id AS uuid)"
                ),
                {"id": row_id},
            )

    err_str = str(exc_info.value).lower()
    assert "immutable" in err_str or "published" in err_str or "p0001" in err_str, (
        f"Expected factor immutability trigger message on DELETE, got: {exc_info.value}"
    )

    # Row must still exist after the failed DELETE
    async with async_engine.connect() as conn:
        count = await conn.execute(
            text(
                "SELECT count(*) FROM ref.factor_catalog "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )
        assert count.scalar() == 1, "Published factor row must survive rejected DELETE"

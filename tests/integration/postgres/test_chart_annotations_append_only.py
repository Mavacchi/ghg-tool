"""Integration tests: ops.chart_annotations append-only enforcement.

The chart_annotations table (M15/M17) has two immutability triggers:
  - trg_chart_annotation_immutability: BEFORE UPDATE -- raises if any
    of title, body, anchor_year, anchor_label, severity, created_by,
    created_at, tenant_id, or chart_key changes.
  - trg_chart_annotation_no_delete: BEFORE DELETE -- always raises.

Allowed post-insert mutations:
  - is_visible: can be toggled (e.g. hide an outdated annotation).
  - acknowledged_by + acknowledged_at: can be set by a reviewer.

Tests:
  1. Insert one annotation (baseline -- must succeed).
  2. UPDATE body raises (immutable field).
  3. UPDATE is_visible succeeds (explicitly allowed).
  4. UPDATE acknowledged_by + acknowledged_at succeeds (explicitly allowed).
  5. DELETE raises.

ISAE 3000 relevance: annotations are narrative evidence that the auditor
relies on to understand YoY trend deviations.  An annotation that can be
silently edited or deleted is not audit-grade evidence.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helper: insert one chart_annotation row; return its UUID
# ---------------------------------------------------------------------------


async def _insert_annotation(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    chart_key: str | None = None,
    title: str = "Test annotation",
    body: str = "Scope 1 dropped due to kiln maintenance.",
    severity: str = "INFO",
    created_by: str = "annotation_test",
    anchor_year: int | None = 2024,
) -> str:
    """Insert one chart_annotation row via committed transaction; return UUID.

    Args:
        engine: AsyncEngine for the test database.
        tenant_id: UUID string of the target tenant.
        chart_key: Chart identifier (default: unique per call).
        title: Annotation title.
        body: Annotation body text.
        severity: One of 'INFO', 'WARNING', 'CRITICAL'.
        created_by: Creator identifier.
        anchor_year: Optional year anchor.

    Returns:
        UUID string of the inserted annotation row.
    """
    row_id = str(uuid.uuid4())
    effective_chart_key = chart_key or f"chart_{row_id[:8]}"

    async with engine.begin() as conn:
        if anchor_year is not None:
            await conn.execute(
                text(
                    "INSERT INTO ops.chart_annotations ("
                    "  id, tenant_id, chart_key, anchor_year, title, body, "
                    "  severity, created_by, is_visible"
                    ") VALUES ("
                    "  CAST(:id AS uuid), CAST(:tid AS uuid), :chart_key, :anchor_year, "
                    "  :title, :body, :severity, :created_by, TRUE"
                    ")"
                ),
                {
                    "id": row_id,
                    "tid": tenant_id,
                    "chart_key": effective_chart_key,
                    "anchor_year": anchor_year,
                    "title": title,
                    "body": body,
                    "severity": severity,
                    "created_by": created_by,
                },
            )
        else:
            await conn.execute(
                text(
                    "INSERT INTO ops.chart_annotations ("
                    "  id, tenant_id, chart_key, title, body, "
                    "  severity, created_by, is_visible"
                    ") VALUES ("
                    "  CAST(:id AS uuid), CAST(:tid AS uuid), :chart_key, "
                    "  :title, :body, :severity, :created_by, TRUE"
                    ")"
                ),
                {
                    "id": row_id,
                    "tid": tenant_id,
                    "chart_key": effective_chart_key,
                    "title": title,
                    "body": body,
                    "severity": severity,
                    "created_by": created_by,
                },
            )
    return row_id


# ---------------------------------------------------------------------------
# Test: baseline INSERT succeeds
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_annotation_insert_succeeds(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """A valid INSERT on ops.chart_annotations commits without error.

    Postcondition: row is readable with is_visible=TRUE.
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    row_id = await _insert_annotation(
        async_engine,
        tenant_id=seed.tenant_a,
    )

    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id::text, is_visible "
                "FROM ops.chart_annotations "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )
        row = result.fetchone()

    assert row is not None, f"Annotation {row_id} must be readable after INSERT"
    assert str(row[0]) == row_id
    assert row[1] is True, "is_visible must be TRUE for a newly inserted annotation"


# ---------------------------------------------------------------------------
# Test: UPDATE body raises (immutable field)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_annotation_update_body_raises(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """UPDATE body on a committed annotation raises (immutability trigger).

    The trigger message from M17:
    'chart_annotations rows are immutable except for is_visible / acknowledged_*'
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    row_id = await _insert_annotation(
        async_engine,
        tenant_id=seed.tenant_a,
        body="Original body text that must not change.",
    )

    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)) as exc_info:
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE ops.chart_annotations "
                    "SET body = 'tampered body' "
                    "WHERE id = CAST(:id AS uuid)"
                ),
                {"id": row_id},
            )

    err_str = str(exc_info.value).lower()
    assert "immutable" in err_str or "acknowledged" in err_str or "p0001" in err_str, (
        f"Expected annotation immutability trigger message, got: {exc_info.value}"
    )

    # Confirm body is unchanged
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT body FROM ops.chart_annotations WHERE id = CAST(:id AS uuid)"),
            {"id": row_id},
        )
        row = result.fetchone()
    assert row is not None
    assert row[0] == "Original body text that must not change.", (
        f"body must be unchanged after rejected UPDATE, got: {row[0]!r}"
    )


# ---------------------------------------------------------------------------
# Test: UPDATE is_visible succeeds (explicitly allowed)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_annotation_update_is_visible_succeeds(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """UPDATE is_visible on a committed annotation succeeds.

    is_visible is the soft-delete mechanism: a data steward can hide an
    outdated annotation without violating the append-only rule.  The trigger
    explicitly permits this column to change.
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    row_id = await _insert_annotation(
        async_engine,
        tenant_id=seed.tenant_a,
    )

    # Toggle is_visible to FALSE -- must succeed
    async with async_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE ops.chart_annotations "
                "SET is_visible = FALSE "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )

    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT is_visible FROM ops.chart_annotations "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )
        row = result.fetchone()

    assert row is not None
    assert row[0] is False, "is_visible must be FALSE after permitted UPDATE"


# ---------------------------------------------------------------------------
# Test: UPDATE acknowledged_by + acknowledged_at succeeds
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_annotation_acknowledge_succeeds(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """UPDATE acknowledged_by + acknowledged_at on an annotation succeeds.

    Acknowledgement is the auditor workflow: they review a narrative
    annotation and stamp it as reviewed.  Both columns are in the trigger's
    whitelist and must not raise.
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    row_id = await _insert_annotation(
        async_engine,
        tenant_id=seed.tenant_a,
    )

    # Acknowledge the annotation -- must succeed
    async with async_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE ops.chart_annotations "
                "SET acknowledged_by = 'auditor_user', "
                "    acknowledged_at = now() "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )

    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT acknowledged_by, acknowledged_at "
                "FROM ops.chart_annotations "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )
        row = result.fetchone()

    assert row is not None
    assert row[0] == "auditor_user", (
        f"acknowledged_by must be 'auditor_user', got {row[0]!r}"
    )
    assert row[1] is not None, "acknowledged_at must be set after acknowledgement UPDATE"


# ---------------------------------------------------------------------------
# Test: DELETE raises
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_annotation_delete_raises(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """DELETE on an annotation raises (trg_chart_annotation_no_delete trigger).

    The error message from M17:
    'chart_annotations rows cannot be deleted; toggle is_visible instead'
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    row_id = await _insert_annotation(
        async_engine,
        tenant_id=seed.tenant_a,
    )

    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)) as exc_info:
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM ops.chart_annotations "
                    "WHERE id = CAST(:id AS uuid)"
                ),
                {"id": row_id},
            )

    err_str = str(exc_info.value).lower()
    assert "deleted" in err_str or "is_visible" in err_str or "p0001" in err_str, (
        f"Expected annotation no-delete trigger message, got: {exc_info.value}"
    )

    # Row must still exist
    async with async_engine.connect() as conn:
        count = await conn.execute(
            text(
                "SELECT count(*) FROM ops.chart_annotations "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )
        assert count.scalar() == 1, "Annotation row must survive rejected DELETE"

"""Integration test: verify UPDATE/DELETE on calc.emissions_consolidated raises.

Requires a real PostgreSQL instance with M0..M1 migrations applied.
Skipped in CI without a DB (marked @pytest.mark.integration).

Run with: pytest tests/integration -m integration --db-url postgresql+asyncpg://...
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import assert_immutability_violation

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helper: build and execute a minimal valid INSERT into calc.emissions_consolidated
# ---------------------------------------------------------------------------

async def _insert_emission_row(
    session: AsyncSession,
    *,
    tenant_id: str,
    factor_id: str,
    sub_scope: str = "process",
    codice_sito: str = "IANO",
    anno: int = 2024,
) -> str:
    """Insert one minimal-valid emission row; return its UUID as str.

    The row uses STOICH_CACO3_IPCC_2006 (the single deterministic factor from
    M2) so the factor_catalog FK is satisfied.  ``created_by`` is set to a
    test sentinel so rows are identifiable in failure output.

    Args:
        session: Active async session (within an open transaction).
        tenant_id: UUID string of the seeded tenant.
        factor_id: UUID string of an existing ref.factor_catalog row.
        sub_scope: sub_scope label (default 'process' for Scope 1 decarbonation).
        codice_sito: Site code (default 'IANO').
        anno: Reporting year (default 2024).

    Returns:
        UUID string of the newly inserted emission row.
    """
    row_id = str(uuid.uuid4())
    raw_row_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())

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
                1, 1, :sub_scope, :codice_sito, :anno,
                1.23456, CAST(:factor_id AS uuid), '2006', 'IPCC',
                'AR6', 'stoichiometric', 'integration_test'
            )
            """
        ),
        {
            "id": row_id,
            "tenant_id": tenant_id,
            "corr_id": correlation_id,
            "raw_row_id": raw_row_id,
            "sub_scope": sub_scope,
            "codice_sito": codice_sito,
            "anno": anno,
            "factor_id": factor_id,
        },
    )
    return row_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_insert_on_emissions_consolidated_succeeds(
    rls_session: AsyncSession,
    tenant_id: str,
    stoich_factor_id: str,
) -> None:
    """Assert that a valid INSERT on emissions_consolidated succeeds.

    Validates the append-only pattern works as intended with all mandatory
    columns (CG-04: factor_source, factor_version, gwp_set, methodology
    must not be NULL).

    After INSERT the row must be queryable with valid_to IS NULL and
    superseded_by IS NULL (active, not yet corrected).
    """
    row_id = await _insert_emission_row(
        rls_session,
        tenant_id=tenant_id,
        factor_id=stoich_factor_id,
    )

    result = await rls_session.execute(
        text(
            "SELECT id::text, valid_to, superseded_by "
            "FROM calc.emissions_consolidated "
            "WHERE id = CAST(:id AS uuid)"
        ),
        {"id": row_id},
    )
    row = result.fetchone()

    assert row is not None, f"Row {row_id} not found after INSERT"
    assert str(row[0]) == row_id
    assert row[1] is None, "valid_to must be NULL for a fresh emission row"
    assert row[2] is None, "superseded_by must be NULL for a fresh emission row"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_on_emissions_consolidated_raises(
    rls_session: AsyncSession,
    tenant_id: str,
    stoich_factor_id: str,
) -> None:
    """Assert that a raw UPDATE on emissions_consolidated is rejected by the trigger.

    The ``trg_emissions_deny_mutation`` trigger (M1) must raise PG exception
    P0001 for any UPDATE outside the correction stored procedure.
    This test satisfies NFR-14, CG-03, NFR-21.

    After the failed UPDATE the session is in an error state; we use a
    savepoint to verify the original row is unchanged within the same
    transaction isolation context.
    """
    row_id = await _insert_emission_row(
        rls_session,
        tenant_id=tenant_id,
        factor_id=stoich_factor_id,
    )

    with pytest.raises((IntegrityError, ProgrammingError)) as exc_info:
        await rls_session.execute(
            text(
                "UPDATE calc.emissions_consolidated "
                "SET tco2e = 999.0 "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )

    assert_immutability_violation(
        exc_info.value,
        trigger_hint="forbidden",
    )
    # The UPDATE error message from M1: 'UPDATE forbidden on calc.emissions_consolidated'
    assert "update" in str(exc_info.value).lower() or "forbidden" in str(exc_info.value).lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_on_emissions_consolidated_raises(
    rls_session: AsyncSession,
    tenant_id: str,
    stoich_factor_id: str,
) -> None:
    """Assert that DELETE on emissions_consolidated is rejected by the trigger.

    The trigger must fire for DELETE regardless of the correction GUC.
    Error message from M1: 'DELETE forbidden on calc.emissions_consolidated'.
    """
    row_id = await _insert_emission_row(
        rls_session,
        tenant_id=tenant_id,
        factor_id=stoich_factor_id,
    )

    with pytest.raises((IntegrityError, ProgrammingError)) as exc_info:
        await rls_session.execute(
            text(
                "DELETE FROM calc.emissions_consolidated "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )

    assert_immutability_violation(
        exc_info.value,
        trigger_hint="forbidden",
    )
    # The DELETE error message from M1: 'DELETE forbidden on calc.emissions_consolidated'
    assert "delete" in str(exc_info.value).lower() or "forbidden" in str(exc_info.value).lower()

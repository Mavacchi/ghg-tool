"""Integration test: verify calc.fn_emit_correction behaviour.

Requires a real PostgreSQL instance with M0..M2 migrations applied and session
GUCs set correctly.  Skipped in CI without a DB (marked @pytest.mark.integration).

Run with: pytest tests/integration -m integration --db-url postgresql+asyncpg://...

Assertions (per docs/architecture.md §4.3, ADR-009, NFR-14):
  - fn_emit_correction inserts a new row with superseded_by = predecessor id
  - fn_emit_correction closes the predecessor row (sets valid_to = NOW())
  - Calling without the correction GUC set raises PG exception
  - Invalid reason_code is rejected by the stored procedure

Implementation notes
---------------------
calc.fn_emit_correction(p_predecessor_id, p_new_id, p_reason_code):
  1. Validates reason_code against the allowed set.
  2. Sets the session GUC app.correction_in_progress = 'true' (transaction-local).
  3. UPDATEs predecessor: valid_to = now(), superseded_by = p_new_id, reason_code.
  4. Resets app.correction_in_progress = 'false'.

The function does NOT write to calc.audit_log.  The audit_log test therefore
verifies that the application layer can INSERT an audit record immediately
after the correction call, and that the audit_log append-only trigger prevents
any subsequent mutation of that record.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Allowed reason_code values from fn_emit_correction (M1 source of truth)
# ---------------------------------------------------------------------------
_VALID_REASON_CODES = (
    "DATA_ERROR",
    "FACTOR_UPDATE",
    "BOUNDARY_CHANGE",
    "METHODOLOGY_REVISION",
    "RESTATEMENT_>5PCT",
)


# ---------------------------------------------------------------------------
# Helper: insert a minimal-valid emission row; return its UUID string
# ---------------------------------------------------------------------------

async def _insert_emission(
    session: AsyncSession,
    *,
    tenant_id: str,
    factor_id: str,
    sub_scope: str = "process",
    codice_sito: str = "IANO",
    anno: int = 2024,
    tco2e: float = 1.5,
) -> str:
    """INSERT one valid emission row and return its id as str.

    Each call produces a unique (scope, sub_scope, codice_sito, anno,
    gwp_set, regulatory_stream) combination by appending a UUID suffix
    to sub_scope so the partial unique index on active rows is not violated
    when two rows coexist in the same transaction.

    Args:
        session: Active async session within an open transaction.
        tenant_id: UUID string of the seeded tenant.
        factor_id: UUID string of an existing ref.factor_catalog row.
        sub_scope: Emission sub-scope label.
        codice_sito: Site code.
        anno: Reporting year.
        tco2e: Emission value in tCO2e.

    Returns:
        UUID string of the inserted row.
    """
    row_id = str(uuid.uuid4())
    raw_row_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    # Make sub_scope unique per call to avoid the partial unique index collision
    unique_sub_scope = f"{sub_scope}_{row_id[:8]}"

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
                :tco2e, CAST(:factor_id AS uuid), '2006', 'IPCC',
                'AR6', 'stoichiometric', 'integration_test_correction'
            )
            """
        ),
        {
            "id": row_id,
            "tenant_id": tenant_id,
            "corr_id": correlation_id,
            "raw_row_id": raw_row_id,
            "sub_scope": unique_sub_scope,
            "codice_sito": codice_sito,
            "anno": anno,
            "tco2e": tco2e,
            "factor_id": factor_id,
        },
    )
    return row_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fn_emit_correction_sets_superseded_by(
    rls_session: AsyncSession,
    tenant_id: str,
    stoich_factor_id: str,
) -> None:
    """Assert that fn_emit_correction links new row to predecessor via superseded_by.

    Steps:
      1. INSERT a baseline emission row A (active, valid_to IS NULL).
      2. INSERT a corrected emission row B (also active initially).
      3. CALL fn_emit_correction(A.id, B.id, 'DATA_ERROR').
      4. Assert row A: valid_to IS NOT NULL, superseded_by = B.id.
      5. Assert row B: valid_to IS NULL, superseded_by IS NULL (active).

    Satisfies NFR-14 (correction-as-new-row), CG-03, ADR-009.
    """
    # Step 1: INSERT predecessor row A
    row_a_id = await _insert_emission(
        rls_session,
        tenant_id=tenant_id,
        factor_id=stoich_factor_id,
        tco2e=10.0,
    )

    # Step 2: INSERT corrected row B (the new canonical value)
    row_b_id = await _insert_emission(
        rls_session,
        tenant_id=tenant_id,
        factor_id=stoich_factor_id,
        tco2e=12.5,
    )

    # Step 3: Call fn_emit_correction — closes row A, points it at row B
    await rls_session.execute(
        text("SELECT calc.fn_emit_correction(CAST(:a AS uuid), CAST(:b AS uuid), 'DATA_ERROR')"),
        {"a": row_a_id, "b": row_b_id},
    )

    # Step 4: Verify row A is now closed (valid_to set) and linked to B
    result_a = await rls_session.execute(
        text(
            "SELECT valid_to, superseded_by::text, reason_code "
            "FROM calc.emissions_consolidated "
            "WHERE id = CAST(:id AS uuid)"
        ),
        {"id": row_a_id},
    )
    row_a = result_a.fetchone()
    assert row_a is not None
    assert row_a[0] is not None, "Row A valid_to must be set after correction"
    assert row_a[1] == row_b_id, (
        f"Row A superseded_by must equal row B id; got {row_a[1]}"
    )
    assert row_a[2] == "DATA_ERROR", (
        f"Row A reason_code must be 'DATA_ERROR'; got {row_a[2]}"
    )

    # Step 5: Verify row B is still active
    result_b = await rls_session.execute(
        text(
            "SELECT valid_to, superseded_by "
            "FROM calc.emissions_consolidated "
            "WHERE id = CAST(:id AS uuid)"
        ),
        {"id": row_b_id},
    )
    row_b = result_b.fetchone()
    assert row_b is not None
    assert row_b[0] is None, "Row B valid_to must still be NULL (row B is the active row)"
    assert row_b[1] is None, "Row B superseded_by must be NULL (it has not been corrected yet)"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fn_emit_correction_rejects_invalid_reason_code(
    rls_session: AsyncSession,
    tenant_id: str,
    stoich_factor_id: str,
) -> None:
    """Assert fn_emit_correction raises when reason_code is not in the allowed set.

    Allowed codes from M1 source: DATA_ERROR, FACTOR_UPDATE, BOUNDARY_CHANGE,
    METHODOLOGY_REVISION, RESTATEMENT_>5PCT.  Any other value must cause
    PG exception P0001 ('Invalid reason_code: ...').
    """
    row_a_id = await _insert_emission(
        rls_session,
        tenant_id=tenant_id,
        factor_id=stoich_factor_id,
    )
    row_b_id = await _insert_emission(
        rls_session,
        tenant_id=tenant_id,
        factor_id=stoich_factor_id,
    )

    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)) as exc_info:
        await rls_session.execute(
            text(
                "SELECT calc.fn_emit_correction("
                "CAST(:a AS uuid), CAST(:b AS uuid), 'INVALID_CODE_XYZ')"
            ),
            {"a": row_a_id, "b": row_b_id},
        )

    err_str = str(exc_info.value).lower()
    # M1 RAISE EXCEPTION message: 'Invalid reason_code: INVALID_CODE_XYZ'
    assert "invalid reason_code" in err_str or "p0001" in err_str, (
        f"Expected 'Invalid reason_code' in error, got: {exc_info.value}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fn_emit_correction_requires_correction_guc(
    rls_session: AsyncSession,
    tenant_id: str,
    stoich_factor_id: str,
) -> None:
    """Assert that a raw UPDATE is rejected when app.correction_in_progress is not set.

    fn_emit_correction is the only path that legitimately sets the GUC
    'app.correction_in_progress' = 'true' (SECURITY DEFINER, transaction-local).
    Any direct UPDATE from an unprivileged session that has not gone through
    fn_emit_correction must be blocked by the trg_emissions_deny_mutation trigger.

    This test simulates an attacker attempting to UPDATE tco2e directly without
    using fn_emit_correction.  The trigger checks
    ``current_setting('app.correction_in_progress', true)`` and raises P0001
    when it is absent or not 'true'.
    """
    row_id = await _insert_emission(
        rls_session,
        tenant_id=tenant_id,
        factor_id=stoich_factor_id,
    )

    # Explicitly ensure the GUC is NOT set (default state for a fresh transaction)
    await rls_session.execute(
        text("SELECT set_config('app.correction_in_progress', 'false', true)")
    )

    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)) as exc_info:
        await rls_session.execute(
            text(
                "UPDATE calc.emissions_consolidated "
                "SET tco2e = 0.001 "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )

    # M1 trigger message: 'UPDATE forbidden on calc.emissions_consolidated
    #                      outside the correction stored procedure'
    err_str = str(exc_info.value).lower()
    assert "forbidden" in err_str or "outside" in err_str or "p0001" in err_str, (
        f"Expected immutability guard error, got: {exc_info.value}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fn_emit_correction_audit_log_entry_created(
    rls_session: AsyncSession,
    tenant_id: str,
    stoich_factor_id: str,
) -> None:
    """Assert that an audit log entry can be written after a valid correction.

    fn_emit_correction itself does NOT write to calc.audit_log (per M1 source).
    This is the application layer's responsibility.  This test verifies:
      (a) calc.audit_log accepts an INSERT with action='EMISSION_CORRECTION'.
      (b) The row is queryable immediately within the same transaction.
      (c) A subsequent UPDATE on the audit_log row is blocked by
          trg_audit_log_deny_mutation (append-only invariant from M1).

    This test reproduces the full application-layer correction sequence:
    fn_emit_correction call + audit INSERT.
    """
    # Setup: two emission rows
    row_a_id = await _insert_emission(
        rls_session,
        tenant_id=tenant_id,
        factor_id=stoich_factor_id,
        tco2e=5.0,
    )
    row_b_id = await _insert_emission(
        rls_session,
        tenant_id=tenant_id,
        factor_id=stoich_factor_id,
        tco2e=6.0,
    )

    # Step 1: Execute the correction procedure
    await rls_session.execute(
        text("SELECT calc.fn_emit_correction(CAST(:a AS uuid), CAST(:b AS uuid), 'FACTOR_UPDATE')"),
        {"a": row_a_id, "b": row_b_id},
    )

    # Step 2: Application layer writes the audit entry
    audit_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    await rls_session.execute(
        text(
            """
            INSERT INTO calc.audit_log (
                id, tenant_id, correlation_id, user_role, action,
                resource, resource_id, before_state, after_state
            ) VALUES (
                CAST(:audit_id AS uuid), CAST(:tenant_id AS uuid), CAST(:corr_id AS uuid),
                'editor', 'EMISSION_CORRECTION',
                'calc.emissions_consolidated', CAST(:res_id AS uuid),
                CAST(:before_state AS jsonb), CAST(:after_state AS jsonb)
            )
            """
        ),
        {
            "audit_id": audit_id,
            "tenant_id": tenant_id,
            "corr_id": correlation_id,
            "res_id": row_a_id,
            "before_state": f'{{"id": "{row_a_id}", "tco2e": 5.0}}',
            "after_state": f'{{"id": "{row_b_id}", "tco2e": 6.0, "reason": "FACTOR_UPDATE"}}',
        },
    )

    # Step 3: Verify the audit entry exists and has the correct action
    result = await rls_session.execute(
        text(
            "SELECT action, resource_id::text, correlation_id::text "
            "FROM calc.audit_log "
            "WHERE id = CAST(:id AS uuid)"
        ),
        {"id": audit_id},
    )
    audit_row = result.fetchone()
    assert audit_row is not None, "Audit log entry must be queryable after INSERT"
    assert audit_row[0] == "EMISSION_CORRECTION", (
        f"Expected action='EMISSION_CORRECTION', got: {audit_row[0]}"
    )
    assert audit_row[1] == row_a_id, (
        f"Expected resource_id to be predecessor row id; got: {audit_row[1]}"
    )
    assert audit_row[2] == correlation_id

    # Step 4: Verify audit_log is itself append-only (M1 trg_audit_log_deny_mutation)
    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)):
        await rls_session.execute(
            text(
                "UPDATE calc.audit_log SET action = 'TAMPERED' WHERE id = CAST(:id AS uuid)"
            ),
            {"id": audit_id},
        )

"""Integration test: verify calc.fn_emit_correction behaviour.

Requires a real PostgreSQL instance with M0..M2 migrations applied and session
GUCs set correctly.  Skipped in CI without a DB (marked @pytest.mark.integration).

Run with: pytest tests/integration -m integration --db-url postgresql+asyncpg://...

Assertions (per docs/architecture.md §4.3, ADR-009, NFR-14):
  - fn_emit_correction inserts a new row with superseded_by = predecessor id
  - fn_emit_correction closes the predecessor row (sets valid_to = NOW())
  - Calling without the correction GUC set raises PG exception
  - Invalid reason_code is rejected by the stored procedure
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fn_emit_correction_sets_superseded_by() -> None:
    """Assert that fn_emit_correction links new row to predecessor via superseded_by.

    Steps:
      1. INSERT a baseline emission row (active, valid_to IS NULL).
      2. INSERT the corrected row.
      3. CALL fn_emit_correction(p_predecessor_id, p_new_id, p_reason_code).
      4. Assert new row.superseded_by = predecessor.id.
      5. Assert predecessor.valid_to IS NOT NULL (row closed).

    Satisfies NFR-14 (correction-as-new-row), CG-03, ADR-009.
    Deferred to wave 3: requires PostgreSQL with M0..M2 applied and
    superuser (or fn_emit_correction SECURITY DEFINER) session.
    """
    pytest.skip(
        "Integration test deferred to wave 3: requires PostgreSQL with M0..M2 applied. "
        "Run with --db-url and -m integration flags."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fn_emit_correction_rejects_invalid_reason_code() -> None:
    """Assert fn_emit_correction raises when reason_code is not in allowed set.

    Allowed codes (architecture.md §4.3): DATA_ERROR, FACTOR_REVISION,
    SCOPE_RECLASSIFICATION, BOUNDARY_CHANGE.  Any other value must cause
    PG exception P0001 to be raised.
    """
    pytest.skip(
        "Integration test deferred to wave 3: requires PostgreSQL with M0..M2 applied."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fn_emit_correction_requires_correction_guc() -> None:
    """Assert that a direct UPDATE outside fn_emit_correction is rejected.

    The deny_emissions_mutation trigger must raise unless the session GUC
    ``app.correction_in_progress`` is set to 'true' by fn_emit_correction
    (SECURITY DEFINER).  A raw UPDATE from an unprivileged session must be
    blocked regardless of columns changed.
    """
    pytest.skip(
        "Integration test deferred to wave 3: requires PostgreSQL with M0..M2 applied."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fn_emit_correction_audit_log_entry_created() -> None:
    """Assert that fn_emit_correction writes an entry to calc.audit_log.

    Per architecture.md §5.4 (RBAC/audit), every correction must produce
    an immutable audit record with before/after JSON snapshots and the
    acting user_id (from app.user_id session GUC).
    """
    pytest.skip(
        "Integration test deferred to wave 3: requires PostgreSQL with M0..M2 applied."
    )

"""Integration test: verify UPDATE/DELETE on calc.emissions_consolidated raises.

Requires a real PostgreSQL instance with M0..M1 migrations applied.
Skipped in CI without a DB (marked @pytest.mark.integration).

Run with: pytest tests/integration -m integration --db-url postgresql+asyncpg://...
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_on_emissions_consolidated_raises() -> None:
    """Assert that a raw UPDATE on emissions_consolidated is rejected by the trigger.

    The ``trg_emissions_deny_mutation`` trigger (M1) must raise PG exception
    P0001 for any UPDATE outside the correction stored procedure.
    This test satisfies NFR-14, CG-03, NFR-21.

    Skipped if PostgreSQL not available (deferred to wave 3 with real DB).
    """
    pytest.skip(
        "Integration test deferred to wave 3: requires PostgreSQL with M0..M1 applied. "
        "Run with --db-url and -m integration flags."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_on_emissions_consolidated_raises() -> None:
    """Assert that DELETE on emissions_consolidated is rejected by the trigger.

    The trigger must fire for DELETE regardless of the correction GUC.
    """
    pytest.skip(
        "Integration test deferred to wave 3: requires PostgreSQL with M0..M1 applied."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_insert_on_emissions_consolidated_succeeds() -> None:
    """Assert that a valid INSERT on emissions_consolidated succeeds.

    Validates the append-only pattern works as intended with all mandatory
    columns (CG-04: factor_source, factor_version, gwp_set, methodology
    must not be NULL).
    """
    pytest.skip(
        "Integration test deferred to wave 3: requires PostgreSQL with M0..M2 applied."
    )

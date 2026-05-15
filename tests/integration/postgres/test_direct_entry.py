"""Integration tests: raw.direct_entry + emissions_consolidated linkage (Task D, M6).

Verifies FR-22 universal traceability:
    - A ``compute_and_insert`` call writes a row to ``raw.direct_entry``.
    - The corresponding ``calc.emissions_consolidated`` row's ``raw_row_id``
      equals the UUID of the ``raw.direct_entry`` row.
    - The two rows share the same ``correlation_id``.
    - ``raw.direct_entry`` is append-only (UPDATE/DELETE blocked by trigger).

Design:
    Tests use real commits (not rollbacks) because the immutability trigger
    fires only on real UPDATE/DELETE.  Tables are truncated in teardown.

Markers: ``integration`` — skipped in standard CI; run via ``make test-integration``.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_tenant_and_site(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    codice_sito: str = "IANO",
) -> None:
    """Insert a minimal tenant and site row for the test.

    Args:
        engine: AsyncEngine for the test container DB.
        tenant_id: UUID string for the new tenant.
        codice_sito: Site code to insert into ref.sites.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO ref.tenants (id, code, legal_name) "
                "VALUES (CAST(:id AS uuid), :code, :name) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": tenant_id,
                "code": f"DE_TC_{tenant_id[:8].upper()}",
                "name": f"DirectEntry Test Tenant {tenant_id[:8]}",
            },
        )

        await conn.execute(
            text(
                "INSERT INTO ref.sites "
                "(id, tenant_id, codice_sito, full_name, role, geography, "
                " country, site_type, is_active) "
                "VALUES ("
                "  gen_random_uuid(), CAST(:tid AS uuid), :cs, :fn, :role, :geo,"
                "  'IT', 'STABILIMENTO_PRODUTTIVO'::ref.site_type_enum, TRUE"
                ") "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "tid": tenant_id,
                "cs": codice_sito,
                "fn": f"{codice_sito} Test Site",
                "role": "production",
                "geo": "IT",
            },
        )


async def _truncate_test_rows(
    engine: AsyncEngine,
    *,
    tenant_id: str,
) -> None:
    """Remove all rows belonging to the test tenant to avoid bleed-between tests.

    Args:
        engine: AsyncEngine for the test container DB.
        tenant_id: UUID string of the tenant to clean up.
    """
    async with engine.begin() as conn:
        # audit_log first (FK from emissions_consolidated)
        await conn.execute(
            text(
                "DELETE FROM calc.audit_log "
                "WHERE tenant_id = CAST(:tid AS uuid)"
            ),
            {"tid": tenant_id},
        )
        # emissions_consolidated references raw.direct_entry via raw_row_id
        await conn.execute(
            text(
                "DELETE FROM calc.emissions_consolidated "
                "WHERE tenant_id = CAST(:tid AS uuid)"
            ),
            {"tid": tenant_id},
        )
        # raw.direct_entry
        await conn.execute(
            text(
                "DELETE FROM raw.direct_entry "
                "WHERE tenant_id = CAST(:tid AS uuid)"
            ),
            {"tid": tenant_id},
        )
        # sites and tenant
        await conn.execute(
            text("DELETE FROM ref.sites WHERE tenant_id = CAST(:tid AS uuid)"),
            {"tid": tenant_id},
        )
        await conn.execute(
            text("DELETE FROM ref.tenants WHERE id = CAST(:tid AS uuid)"),
            {"tid": tenant_id},
        )


def _build_mock_user(tenant_id: str) -> MagicMock:
    """Build a minimal CurrentUser-like mock.

    Args:
        tenant_id: UUID string to inject as the tenant.

    Returns:
        A MagicMock with sub, tenant_id, and role attributes.
    """
    user = MagicMock()
    user.sub = str(uuid.uuid4())
    user.tenant_id = tenant_id
    user.role = "editor"
    return user


def _build_mock_catalog(
    *,
    factor_value: Decimal = Decimal("0.27"),
    factor_id: str = "LB_IT_GRID_ISPRA_2024",
) -> MagicMock:
    """Build an in-memory factor catalog mock for use in direct compute_and_insert calls.

    Args:
        factor_value: Emission factor value (default IT grid 0.27 kgCO2/kWh).
        factor_id: Factor ID string.

    Returns:
        MagicMock satisfying the FactorCatalogPort interface.
    """
    from ghg_tool.domain.ports.factor_catalog import FactorRecord  # noqa: PLC0415

    factor = FactorRecord(
        factor_id=factor_id,
        version="2025",
        value=factor_value,
        unit="kg CO2 / kWh",
        source="ISPRA",
        gwp_set="AR6",
        vintage="2024",
        is_tbc=False,
    )

    catalog = MagicMock()
    catalog.get.return_value = factor
    catalog.get_biogenic_share.return_value = None
    return catalog


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_and_insert_writes_raw_direct_entry(
    async_engine: AsyncEngine,
    seed_tenants: Any,
) -> None:
    """Task D, FR-22: compute_and_insert writes a row to raw.direct_entry
    with the same correlation_id as the emissions_consolidated row, and
    emissions_consolidated.raw_row_id = raw.direct_entry.id.

    This is the primary traceability assertion for M6 decision #1.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: PLC0415

    from ghg_tool.api.schemas.calc_schemas import CalcInputRequest  # noqa: PLC0415
    from ghg_tool.application.services.auto_calc_service import compute_and_insert  # noqa: PLC0415

    tenant_id = seed_tenants.tenant_a
    codice_sito = "IANO"

    await _insert_tenant_and_site(async_engine, tenant_id=tenant_id, codice_sito=codice_sito)

    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    user = _build_mock_user(tenant_id)
    catalog = _build_mock_catalog()

    fixed_cid = str(uuid.uuid4())

    try:
        async with session_factory() as session:
            # Set GUCs that the service expects (tenant isolation)
            await session.execute(
                text("SET LOCAL app.tenant_id = :tid"),
                {"tid": tenant_id},
            )
            await session.execute(
                text("SET LOCAL app.role = 'editor'"),
            )

            req = CalcInputRequest(
                scope=2,
                sub_scope="lb",
                anno=2024,
                codice_sito=codice_sito,
                quantita=Decimal("10000"),
                unita="kWh",
                gwp_set="AR6",
            )

            with patch(
                "ghg_tool.application.services.auto_calc_service.get_correlation_id",
                return_value=fixed_cid,
            ):
                result = await compute_and_insert(
                    req,
                    factor_catalog=catalog,
                    session=session,
                    user=user,
                )

            await session.commit()

        emission_id = str(result.emission_id)

        # Verify raw.direct_entry row exists
        async with async_engine.begin() as conn:
            raw_row = await conn.execute(
                text(
                    "SELECT id::text, correlation_id::text, tco2e, "
                    "       factor_id, inserted_by, request_payload "
                    "FROM raw.direct_entry "
                    "WHERE correlation_id = CAST(:cid AS uuid) "
                    "  AND tenant_id = CAST(:tid AS uuid)"
                ),
                {"cid": fixed_cid, "tid": tenant_id},
            )
            raw_entry = raw_row.mappings().first()

        assert raw_entry is not None, (
            f"No raw.direct_entry row found for correlation_id={fixed_cid}"
        )
        assert str(raw_entry["factor_id"]) == "LB_IT_GRID_ISPRA_2024"
        assert Decimal(str(raw_entry["tco2e"])) == Decimal("2.700000")
        raw_entry_id = str(raw_entry["id"])

        # Verify emissions_consolidated.raw_row_id == raw.direct_entry.id
        async with async_engine.begin() as conn:
            em_row = await conn.execute(
                text(
                    "SELECT raw_row_id::text, correlation_id::text "
                    "FROM calc.emissions_consolidated "
                    "WHERE id = CAST(:eid AS uuid)"
                ),
                {"eid": emission_id},
            )
            em = em_row.mappings().first()

        assert em is not None, f"No emissions_consolidated row for id={emission_id}"
        assert str(em["raw_row_id"]) == raw_entry_id, (
            f"raw_row_id mismatch: emissions has {em['raw_row_id']!r}, "
            f"raw.direct_entry has {raw_entry_id!r}"
        )
        assert str(em["correlation_id"]) == fixed_cid, (
            "correlation_id must match between raw.direct_entry and emissions_consolidated"
        )

    finally:
        await _truncate_test_rows(async_engine, tenant_id=tenant_id)


@pytest.mark.asyncio
async def test_raw_direct_entry_is_append_only(
    async_engine: AsyncEngine,
    seed_tenants: Any,
) -> None:
    """raw.direct_entry must block UPDATE and DELETE via the ops.deny_mutation() trigger.

    This mirrors the append-only pattern of raw.scope1_combustion established
    in migration M0 and extended to raw.direct_entry in M6 (decision #1).
    """
    tenant_id = seed_tenants.tenant_b

    # Insert a raw.direct_entry row directly (bypassing the application layer)
    raw_id = str(uuid.uuid4())
    corr_id = str(uuid.uuid4())

    try:
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO raw.direct_entry "
                    "(id, tenant_id, correlation_id, inserted_by, "
                    " request_payload, factor_id, factor_vintage, tco2e) "
                    "VALUES ("
                    "  CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:cid AS uuid),"
                    "  :inserted_by, CAST(:payload AS jsonb), :fid, :fv, :tco2e"
                    ")"
                ),
                {
                    "id": raw_id,
                    "tid": tenant_id,
                    "cid": corr_id,
                    "inserted_by": "test_runner",
                    "payload": json.dumps({"test": True}),
                    "fid": "TEST_FACTOR_DIRECT_ENTRY",
                    "fv": 2024,
                    "tco2e": 1.23,
                },
            )

        # Attempt UPDATE — must be blocked by the deny_mutation trigger
        with pytest.raises((DBAPIError, Exception)) as exc_info:
            async with async_engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE raw.direct_entry SET tco2e = 999.0 "
                        "WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": raw_id},
                )

        err_str = str(exc_info.value).lower()
        assert "immutable" in err_str or "deny" in err_str, (
            f"Expected immutability error from trigger, got: {exc_info.value}"
        )

        # Attempt DELETE — must also be blocked
        with pytest.raises((DBAPIError, Exception)) as exc_info2:
            async with async_engine.begin() as conn:
                await conn.execute(
                    text(
                        "DELETE FROM raw.direct_entry WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": raw_id},
                )

        err_str2 = str(exc_info2.value).lower()
        assert "immutable" in err_str2 or "deny" in err_str2, (
            f"Expected immutability error from trigger, got: {exc_info2.value}"
        )

    finally:
        # Cleanup: use superuser direct delete (bypasses trigger? No — we need to
        # leave the row since we cannot delete it through the trigger. Instead we
        # verify the row is still there and accept it as integration DB noise.)
        # The test container is ephemeral so this row will be cleaned up on
        # container teardown.
        pass

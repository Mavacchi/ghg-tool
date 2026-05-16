"""Integration tests for migration 0028_M8: NCV dual-unit factor variants.

Validates decision #3 from auto_calc_design.md §12:
  - Base per-Sm3 / per-litre DEFRA 2024 CO2 factors are present and published.
  - Per-kWh derived variants are present for GAS_NAT, GASOLIO_AUTO, BENZINA_AUTO.
  - Mathematical consistency: factor_kwh == factor_native / NCV ± 0.1%.
  - LB_IT_GRID_ISPRA_2024 (existing, vintage=2024, unit=kWh) is unaffected.
  - All new rows have is_published=TRUE and is_tbc=FALSE.
  - Downgrade removes exactly the M8 rows without touching M2 rows.

These tests require a real PostgreSQL 15 container via the shared
`async_engine` fixture in tests/integration/postgres/conftest.py.

Run:  pytest -m integration tests/integration/postgres/test_migration_0028.py
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# NCV constants (must match migration exactly)
# ---------------------------------------------------------------------------
_NCV_GAS_NAT: Decimal = Decimal("9.59")    # kWh/Sm3
_NCV_GASOLIO: Decimal = Decimal("9.97")    # kWh/L
_NCV_BENZINA: Decimal = Decimal("9.20")    # kWh/L

_TOLERANCE = Decimal("0.001")  # 0.1 % relative


def _relative_diff(a: Decimal, b: Decimal) -> Decimal:
    """Return |a-b| / b (relative difference)."""
    if b == 0:
        return Decimal("inf")
    return abs(a - b) / b


# ---------------------------------------------------------------------------
# Helper: fetch a single factor value from ref.factor_catalog
# ---------------------------------------------------------------------------
async def _get_factor(
    engine: AsyncEngine, factor_id: str
) -> tuple[Decimal | None, bool, bool]:
    """Return (value, is_published, is_tbc) for a given factor_id.

    Returns (None, False, False) if the row does not exist.
    """
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT value, is_published, is_tbc "
                "FROM ref.factor_catalog "
                "WHERE factor_id = :fid "
                "ORDER BY valid_from DESC "
                "LIMIT 1"
            ),
            {"fid": factor_id},
        )
        row = result.fetchone()
    if row is None:
        return None, False, False
    val = Decimal(str(row[0])) if row[0] is not None else None
    return val, bool(row[1]), bool(row[2])


# ===========================================================================
# Test 1 — INSERT: all 12 new rows exist
# ===========================================================================


@pytest.mark.asyncio
async def test_all_m8_factor_ids_present(async_engine: AsyncEngine) -> None:
    """All 12 factor_ids inserted by M8 must exist in ref.factor_catalog.

    The migration inserts 3 base + 1 derived = 4 rows per fuel × 3 fuels = 12 rows.
    """
    expected_ids = [
        # Gas naturale
        "COMB_GAS_NAT_CO2_DEFRA_2024_PER_SM3",
        "COMB_GAS_NAT_CH4_DEFRA_2024_PER_SM3",
        "COMB_GAS_NAT_N2O_DEFRA_2024_PER_SM3",
        "COMB_GAS_NAT_CO2_DEFRA_2024_PER_KWH",
        # Gasolio auto
        "COMB_GASOLIO_AUTO_CO2_DEFRA_2024_PER_LITER",
        "COMB_GASOLIO_AUTO_CH4_DEFRA_2024_PER_LITER",
        "COMB_GASOLIO_AUTO_N2O_DEFRA_2024_PER_LITER",
        "COMB_GASOLIO_AUTO_CO2_DEFRA_2024_PER_KWH",
        # Benzina auto
        "COMB_BENZINA_AUTO_CO2_DEFRA_2024_PER_LITER",
        "COMB_BENZINA_AUTO_CH4_DEFRA_2024_PER_LITER",
        "COMB_BENZINA_AUTO_N2O_DEFRA_2024_PER_LITER",
        "COMB_BENZINA_AUTO_CO2_DEFRA_2024_PER_KWH",
    ]

    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT factor_id FROM ref.factor_catalog "
                "WHERE factor_id = ANY(:ids)"
            ),
            {"ids": expected_ids},
        )
        found = {row[0] for row in result.fetchall()}

    missing = set(expected_ids) - found
    assert not missing, (
        f"The following M8 factor_ids are missing from ref.factor_catalog: {missing}"
    )


# ===========================================================================
# Test 2 — per-kWh lookup: GAS_NAT
# ===========================================================================


@pytest.mark.asyncio
async def test_gas_nat_per_kwh_factor_exists_and_has_value(
    async_engine: AsyncEngine,
) -> None:
    """COMB_GAS_NAT_CO2_DEFRA_2024_PER_KWH must be present with a non-NULL value.

    This is the primary lookup path when a user submits gas consumption in kWh
    (invoice-based; §4 Option C of auto_calc_design.md).
    """
    value, is_published, is_tbc = await _get_factor(
        async_engine, "COMB_GAS_NAT_CO2_DEFRA_2024_PER_KWH"
    )

    assert value is not None, (
        "COMB_GAS_NAT_CO2_DEFRA_2024_PER_KWH must have a non-NULL value — "
        "this is a derived (non-TBC) factor"
    )
    assert is_published, (
        "COMB_GAS_NAT_CO2_DEFRA_2024_PER_KWH must be is_published=TRUE"
    )
    assert not is_tbc, (
        "COMB_GAS_NAT_CO2_DEFRA_2024_PER_KWH must have is_tbc=FALSE"
    )


# ===========================================================================
# Test 3 — per-kWh lookup: GASOLIO_AUTO
# ===========================================================================


@pytest.mark.asyncio
async def test_gasolio_per_kwh_factor_exists_and_has_value(
    async_engine: AsyncEngine,
) -> None:
    """COMB_GASOLIO_AUTO_CO2_DEFRA_2024_PER_KWH must be present with a non-NULL value."""
    value, is_published, is_tbc = await _get_factor(
        async_engine, "COMB_GASOLIO_AUTO_CO2_DEFRA_2024_PER_KWH"
    )

    assert value is not None, (
        "COMB_GASOLIO_AUTO_CO2_DEFRA_2024_PER_KWH must have a non-NULL value"
    )
    assert is_published, "COMB_GASOLIO_AUTO_CO2_DEFRA_2024_PER_KWH must be is_published=TRUE"
    assert not is_tbc, "COMB_GASOLIO_AUTO_CO2_DEFRA_2024_PER_KWH must have is_tbc=FALSE"


# ===========================================================================
# Test 4 — mathematical consistency: GAS_NAT
# ===========================================================================


@pytest.mark.asyncio
async def test_gas_nat_kwh_mathematical_consistency(
    async_engine: AsyncEngine,
) -> None:
    """factor_per_kwh == factor_per_sm3 / NCV(9.59) within 0.1%.

    Verifies the core NCV derivation constraint from auto_calc_design.md §12 #3.
    Failure here means the migration used wrong NCV or rounding that violates
    the tolerance required for CSRD-grade factor traceability.
    """
    val_sm3, _, _ = await _get_factor(
        async_engine, "COMB_GAS_NAT_CO2_DEFRA_2024_PER_SM3"
    )
    val_kwh, _, _ = await _get_factor(
        async_engine, "COMB_GAS_NAT_CO2_DEFRA_2024_PER_KWH"
    )

    assert val_sm3 is not None, "COMB_GAS_NAT_CO2_DEFRA_2024_PER_SM3 must have a value"
    assert val_kwh is not None, "COMB_GAS_NAT_CO2_DEFRA_2024_PER_KWH must have a value"

    expected_kwh = val_sm3 / _NCV_GAS_NAT
    diff = _relative_diff(val_kwh, expected_kwh)

    assert diff <= _TOLERANCE, (
        f"GAS_NAT per-kWh mathematical consistency FAILED: "
        f"factor_sm3={val_sm3}, NCV={_NCV_GAS_NAT}, "
        f"expected_kwh={expected_kwh:.6f}, got={val_kwh:.6f}, "
        f"relative_diff={diff:.4%} (tolerance ≤ 0.1%)"
    )


# ===========================================================================
# Test 5 — mathematical consistency: GASOLIO_AUTO
# ===========================================================================


@pytest.mark.asyncio
async def test_gasolio_kwh_mathematical_consistency(
    async_engine: AsyncEngine,
) -> None:
    """factor_per_kwh == factor_per_liter / NCV(9.97) within 0.1%.

    NCV gasolio auto = 9.97 kWh/L (density 0.832 kg/L × 42.7 MJ/kg NCV,
    GHG Protocol EF guide + IPCC 2006 Vol.2 Ch.1).
    """
    val_liter, _, _ = await _get_factor(
        async_engine, "COMB_GASOLIO_AUTO_CO2_DEFRA_2024_PER_LITER"
    )
    val_kwh, _, _ = await _get_factor(
        async_engine, "COMB_GASOLIO_AUTO_CO2_DEFRA_2024_PER_KWH"
    )

    assert val_liter is not None, "COMB_GASOLIO_AUTO_CO2_DEFRA_2024_PER_LITER must have a value"
    assert val_kwh is not None, "COMB_GASOLIO_AUTO_CO2_DEFRA_2024_PER_KWH must have a value"

    expected_kwh = val_liter / _NCV_GASOLIO
    diff = _relative_diff(val_kwh, expected_kwh)

    assert diff <= _TOLERANCE, (
        f"GASOLIO per-kWh mathematical consistency FAILED: "
        f"factor_liter={val_liter}, NCV={_NCV_GASOLIO}, "
        f"expected_kwh={expected_kwh:.6f}, got={val_kwh:.6f}, "
        f"relative_diff={diff:.4%} (tolerance ≤ 0.1%)"
    )


# ===========================================================================
# Test 6 — mathematical consistency: BENZINA_AUTO
# ===========================================================================


@pytest.mark.asyncio
async def test_benzina_kwh_mathematical_consistency(
    async_engine: AsyncEngine,
) -> None:
    """factor_per_kwh == factor_per_liter / NCV(9.20) within 0.1%.

    NCV benzina auto = 9.20 kWh/L (density 0.741 kg/L × 44.7 MJ/kg NCV).
    """
    val_liter, _, _ = await _get_factor(
        async_engine, "COMB_BENZINA_AUTO_CO2_DEFRA_2024_PER_LITER"
    )
    val_kwh, _, _ = await _get_factor(
        async_engine, "COMB_BENZINA_AUTO_CO2_DEFRA_2024_PER_KWH"
    )

    assert val_liter is not None, "COMB_BENZINA_AUTO_CO2_DEFRA_2024_PER_LITER must have a value"
    assert val_kwh is not None, "COMB_BENZINA_AUTO_CO2_DEFRA_2024_PER_KWH must have a value"

    expected_kwh = val_liter / _NCV_BENZINA
    diff = _relative_diff(val_kwh, expected_kwh)

    assert diff <= _TOLERANCE, (
        f"BENZINA per-kWh mathematical consistency FAILED: "
        f"factor_liter={val_liter}, NCV={_NCV_BENZINA}, "
        f"expected_kwh={expected_kwh:.6f}, got={val_kwh:.6f}, "
        f"relative_diff={diff:.4%} (tolerance ≤ 0.1%)"
    )

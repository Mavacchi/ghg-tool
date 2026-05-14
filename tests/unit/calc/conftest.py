"""Shared pytest fixtures for calc-module unit tests.

Provides:
  * ``InMemoryFactorCatalog`` — test double satisfying ``FactorCatalogPort``.
  * ``ar6_gwp`` and ``ar5_gwp`` — concrete ``GWPSetTable`` instances.
  * Common factor-seed dictionaries with pinned numeric values so the calc
    modules can be exercised end-to-end without the real DB.

No database, no filesystem.  All fixtures are pure-Python.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from decimal import Decimal

import pytest

from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.exceptions.calc_errors import MissingFactorError
from ghg_tool.domain.ports.factor_catalog import FactorRecord
from ghg_tool.domain.ports.gwp_table import GWPSetTable
from ghg_tool.domain.value_objects.gwp_set import AR5, AR6


class InMemoryFactorCatalog:
    """Test-double ``FactorCatalogPort`` backed by an in-memory dict."""

    def __init__(self, seed: dict[tuple[str, str], FactorRecord]) -> None:
        """Initialise with a pre-seeded mapping.

        Args:
            seed: Mapping ``(factor_id, gwp_set) -> FactorRecord``.
        """
        self._seed = dict(seed)

    def get(
        self,
        factor_id: str,
        *,
        gwp_set: str,
        vintage_year: int | None = None,  # noqa: ARG002 — interface uniformity
    ) -> FactorRecord:
        """Look up by (factor_id, gwp_set) — raises if absent.

        Args:
            factor_id: Catalog key.
            gwp_set: 'AR6' or 'AR5'.
            vintage_year: Ignored (deterministic seed).

        Returns:
            The matching ``FactorRecord``.

        Raises:
            MissingFactorError: If the key is not seeded.
        """
        key = (factor_id, gwp_set)
        if key not in self._seed:
            raise MissingFactorError(
                f"InMemoryFactorCatalog: missing key {key!r}"
            )
        return self._seed[key]

    def get_biogenic_share(
        self,
        factor_id: str,
        *,
        gwp_set: str,
    ) -> Decimal | None:
        """Return biogenic CO2 share if the seeded record carries one.

        Args:
            factor_id: Catalog key.
            gwp_set: 'AR6' or 'AR5'.

        Returns:
            Biogenic share or ``None``.
        """
        key = (factor_id, gwp_set)
        if key not in self._seed:
            return None
        return self._seed[key].biogenic_co2_kg_per_unit


def _factor(
    factor_id: str,
    value: str,
    *,
    unit: str = "kg CO2e / unit",
    source: str = "DEFRA",
    gwp_set: str = "AR6",
    biogenic: str | None = None,
) -> FactorRecord:
    """Build a ``FactorRecord`` succinctly.

    Args:
        factor_id: Factor identifier.
        value: Decimal-string numeric value.
        unit: Unit string.
        source: Provider.
        gwp_set: GWP set.
        biogenic: Optional biogenic share as decimal-string.

    Returns:
        Constructed ``FactorRecord``.
    """
    return FactorRecord(
        factor_id=factor_id,
        version="2025",
        value=Decimal(value),
        unit=unit,
        source=source,
        gwp_set=gwp_set,
        biogenic_co2_kg_per_unit=Decimal(biogenic) if biogenic is not None else None,
        vintage="2025",
        is_tbc=False,
    )


@pytest.fixture()
def factor_seed() -> dict[tuple[str, str], FactorRecord]:
    """Seed dict covering every factor_id used across the 16 calc modules.

    Values are illustrative (not the real DEFRA / ISPRA numbers — which
    remain TBC at Phase 5 anyway).  What matters for unit testing is
    arithmetic correctness.

    Returns:
        Mapping for ``InMemoryFactorCatalog`` (AR6 + AR5 entries).
    """
    seed: dict[tuple[str, str], FactorRecord] = {}
    for gwp_code in ("AR6", "AR5"):
        # Scope 1 combustion (kg substance / Sm3 or litre)
        for fuel, co2_v, ch4_v, n2o_v in (
            ("GAS_NAT", "2.0", "0.0001", "0.00001"),
            ("GASOLIO", "2.7", "0.0002", "0.00002"),
            ("BENZINA", "2.3", "0.0003", "0.00003"),
        ):
            seed[(f"COMB_{fuel}_CO2_DEFRA_2025", gwp_code)] = _factor(
                f"COMB_{fuel}_CO2_DEFRA_2025", co2_v, gwp_set=gwp_code,
            )
            seed[(f"COMB_{fuel}_CH4_DEFRA_2025", gwp_code)] = _factor(
                f"COMB_{fuel}_CH4_DEFRA_2025", ch4_v, gwp_set=gwp_code,
            )
            seed[(f"COMB_{fuel}_N2O_DEFRA_2025", gwp_code)] = _factor(
                f"COMB_{fuel}_N2O_DEFRA_2025", n2o_v, gwp_set=gwp_code,
            )
        # Stoichiometric process — fixed value 0.4397
        seed[("STOICH_CACO3_IPCC_2006", gwp_code)] = _factor(
            "STOICH_CACO3_IPCC_2006", "0.4397", unit="t CO2 / t CaCO3",
            source="IPCC", gwp_set=gwp_code,
        )
        # Scope 2 LB / MB
        seed[("LB_IT_GRID_ISPRA_2024", gwp_code)] = _factor(
            "LB_IT_GRID_ISPRA_2024", "0.27", unit="kg CO2 / kWh",
            source="ISPRA", gwp_set=gwp_code,
        )
        seed[("MB_GO_ZERO", gwp_code)] = _factor(
            "MB_GO_ZERO", "0", unit="kg CO2e / kWh",
            source="GHG_Protocol", gwp_set=gwp_code,
        )
        seed[("MB_IT_RESIDUAL_AIB_2024", gwp_code)] = _factor(
            "MB_IT_RESIDUAL_AIB_2024", "0.44", unit="kg CO2e / kWh",
            source="AIB", gwp_set=gwp_code,
        )
        # Cat 3 WTT + T&D
        for fuel in ("GAS_NAT", "GASOLIO", "BENZINA"):
            seed[(f"WTT_{fuel}_DEFRA_2025", gwp_code)] = _factor(
                f"WTT_{fuel}_DEFRA_2025", "0.029",
                unit="kg CO2e / unit", gwp_set=gwp_code,
            )
        seed[("WTT_ELEC_DEFRA_2025", gwp_code)] = _factor(
            "WTT_ELEC_DEFRA_2025", "0.022", unit="kg CO2e / kWh",
            gwp_set=gwp_code,
        )
        seed[("TND_ELEC_IT_DEFRA_2025", gwp_code)] = _factor(
            "TND_ELEC_IT_DEFRA_2025", "0.017", unit="kg CO2e / kWh",
            gwp_set=gwp_code,
        )
        # Cat 4 / Cat 9 freight
        seed[("FREIGHT_HGV_DEFRA_2025", gwp_code)] = _factor(
            "FREIGHT_HGV_DEFRA_2025", "0.106", unit="kg CO2e / tkm",
            gwp_set=gwp_code,
        )
        seed[("FREIGHT_RAIL_DEFRA_2025", gwp_code)] = _factor(
            "FREIGHT_RAIL_DEFRA_2025", "0.028", unit="kg CO2e / tkm",
            gwp_set=gwp_code,
        )
        seed[("FREIGHT_SEA_DEFRA_2025", gwp_code)] = _factor(
            "FREIGHT_SEA_DEFRA_2025", "0.005", unit="kg CO2e / tkm",
            gwp_set=gwp_code,
        )
        # Cat 5 waste
        for waste_id in (
            "WASTE_LANDFILL_PERIC_DEFRA_2025",
            "WASTE_LANDFILL_NONPERIC_DEFRA_2025",
            "WASTE_RECYCLE_PERIC_DEFRA_2025",
            "WASTE_RECYCLE_NONPERIC_DEFRA_2025",
        ):
            seed[(waste_id, gwp_code)] = _factor(
                waste_id, "12.5", unit="kg CO2e / tonne",
                gwp_set=gwp_code,
            )
        # Cat 6 travel
        for tid in (
            "TRAVEL_SPEND_FLIGHTS_DEFRA_2025",
            "TRAVEL_SPEND_HIRECAR_DEFRA_2025",
            "TRAVEL_SPEND_HOTEL_DEFRA_2025",
        ):
            seed[(tid, gwp_code)] = _factor(
                tid, "0.30", unit="kg CO2e / GBP", gwp_set=gwp_code,
            )
        # Cat 7 commuting
        seed[("COMMUTE_CAR_DEFRA_2025", gwp_code)] = _factor(
            "COMMUTE_CAR_DEFRA_2025", "0.17", unit="kg CO2e / km",
            gwp_set=gwp_code,
        )
        # Cat 1 mass-based ecoinvent — illustrative pinned values
        for fid in (
            "ECOINV_CLAY_V3_10", "ECOINV_FELDSPAR_V3_10",
            "ECOINV_SILICA_V3_10", "ECOINV_FRIT_V3_10",
            "ECOINV_PIGMENT_V3_10", "ECOINV_ADDITIVES_V3_10",
            "ECOINV_LDPE_V3_10", "ECOINV_PP_V3_10",
        ):
            seed[(fid, gwp_code)] = _factor(
                fid, "0.5", unit="kg CO2e / kg", source="ecoinvent v3.10",
                gwp_set=gwp_code,
            )
        # ADR-007 cardboard / pallet — biogenic share populated
        seed[("ECOINV_CARDBOARD_V3_10", gwp_code)] = _factor(
            "ECOINV_CARDBOARD_V3_10", "1.2",
            unit="kg CO2e / kg", source="ecoinvent v3.10",
            gwp_set=gwp_code, biogenic="0.8",
        )
        seed[("ECOINV_PALLET_V3_10", gwp_code)] = _factor(
            "ECOINV_PALLET_V3_10", "0.6",
            unit="kg CO2e / kg", source="ecoinvent v3.10",
            gwp_set=gwp_code, biogenic="0.4",
        )
        # Cat 1 spend-based EXIOBASE
        seed[("EXIO_SERVICES_NACE_M", gwp_code)] = _factor(
            "EXIO_SERVICES_NACE_M", "0.25",
            unit="kg CO2e / EUR", source="EXIOBASE",
            gwp_set=gwp_code,
        )
        # Cat 2 spend-based EXIOBASE
        seed[("EXIO_MACHINERY_NACE_C28", gwp_code)] = _factor(
            "EXIO_MACHINERY_NACE_C28", "0.40",
            unit="kg CO2e / EUR", source="EXIOBASE",
            gwp_set=gwp_code,
        )
        seed[("EXIO_CONSUMABLES_NACE_C27", gwp_code)] = _factor(
            "EXIO_CONSUMABLES_NACE_C27", "0.32",
            unit="kg CO2e / EUR", source="EXIOBASE",
            gwp_set=gwp_code,
        )
        # Cat 12 EOL
        seed[("ECOINV_LANDFILL_INERT_V3_10", gwp_code)] = _factor(
            "ECOINV_LANDFILL_INERT_V3_10", "8.0",
            unit="kg CO2e / kg", source="ecoinvent v3.10",
            gwp_set=gwp_code,
        )
        seed[("ECOINV_CDW_RECYCLE_V3_10", gwp_code)] = _factor(
            "ECOINV_CDW_RECYCLE_V3_10", "2.0",
            unit="kg CO2e / kg", source="ecoinvent v3.10",
            gwp_set=gwp_code,
        )
    return seed


@pytest.fixture()
def catalog(factor_seed: dict[tuple[str, str], FactorRecord]) -> InMemoryFactorCatalog:
    """Build an in-memory factor catalog from the seed.

    Args:
        factor_seed: Seed mapping.

    Returns:
        ``InMemoryFactorCatalog`` instance.
    """
    return InMemoryFactorCatalog(factor_seed)


@pytest.fixture()
def ar6_gwp() -> GWPSetTable:
    """AR6 GWPSetTable fixture.

    Returns:
        Concrete ``GWPSetTable`` wrapping ``AR6``.
    """
    return GWPSetTable(AR6)


@pytest.fixture()
def ar5_gwp() -> GWPSetTable:
    """AR5 GWPSetTable fixture.

    Returns:
        Concrete ``GWPSetTable`` wrapping ``AR5``.
    """
    return GWPSetTable(AR5)


@pytest.fixture()
def correlation_id() -> uuid.UUID:
    """Deterministic correlation_id for one test session.

    Returns:
        Fixed UUID5 value (deterministic across runs).
    """
    return uuid.UUID("12345678-1234-5678-1234-567812345678")


# ---------------------------------------------------------------------------
# Helpers re-exported for module-specific tests
# ---------------------------------------------------------------------------

def sum_tco2e(records: Iterable[EmissionRecord]) -> Decimal:
    """Sum ``tco2e`` over an iterable of records.

    Args:
        records: Iterable of EmissionRecords.

    Returns:
        Sum as ``Decimal``.
    """
    total = Decimal("0")
    for r in records:
        total += r.tco2e
    return total

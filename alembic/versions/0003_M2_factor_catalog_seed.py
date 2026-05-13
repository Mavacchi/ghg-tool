"""M2 — Factor catalog seed: 38 entries from methodology_validation.md §11.

Deterministic values are inserted immediately.  TBC values are inserted with
``value=NULL`` and ``is_tbc=TRUE``.  Licence-restricted values are inserted
with ``value=NULL`` and ``is_licence_only=TRUE``.

Biogenic companion fields: ECOINV_CARDBOARD_V3_10 and ECOINV_PALLET_V3_10
have ``biogenic_co2_kg_per_unit`` set to NULL + is_tbc=TRUE (ADR-007 pending
licence retrieval at Phase 5, OI-9).

Revision: 0003_M2
Revises: 0002_M1
"""

from __future__ import annotations

from alembic import op

revision: str = "0003_M2"
down_revision: str = "0002_M1"
branch_labels: str | None = None
depends_on: str | None = None

# SQL template for inserting a factor row via subquery tenant join
_INSERT_FACTOR = """
INSERT INTO ref.factor_catalog
    (tenant_id, factor_id, version, substance, scope, category, source,
     value, is_licence_only, is_tbc, biogenic_co2_kg_per_unit,
     unit, gwp_set, vintage, valid_from, applicability_note,
     published_by, is_published)
SELECT t.id,
    {factor_id!r}, {version!r}, {substance!r}, {scope}, {category!r}, {source!r},
    {value}, {is_licence_only}, {is_tbc}, {biogenic},
    {unit!r}, {gwp_set!r}, {vintage!r}, {valid_from!r}, {note!r},
    'system_seed', FALSE
FROM ref.tenants t WHERE t.code = 'CERAMIC_TILE_CO';
"""


def _insert(
    factor_id: str,
    substance: str,
    scope: int,
    category: str,
    source: str,
    version: str,
    value: float | None,
    unit: str,
    gwp_set: str,
    vintage: str,
    note: str,
    is_licence_only: bool = False,
    is_tbc: bool = False,
    biogenic: float | None = None,
) -> None:
    """Execute a single factor catalog INSERT.

    Args:
        factor_id: Unique factor identifier per methodology_validation.md §11.
        substance: Human-readable substance or activity description.
        scope: GHG scope (1, 2, or 3).
        category: Factor category label (e.g. 'Cat 1', 'LB', 'Cat 3a').
        source: Authoritative source code (DEFRA, ISPRA, ecoinvent, etc.).
        version: Source version string.
        value: Numeric emission factor value; None for TBC or licence-only.
        unit: Emission factor unit string.
        gwp_set: GWP set identifier ('AR6', 'AR5', 'n/a').
        vintage: Factor vintage year or 'n/a' for chemistry-based factors.
        note: Applicability note.
        is_licence_only: True when the factor value is licence-restricted.
        is_tbc: True when the numeric value is pending pinning.
        biogenic: Biogenic CO2 companion field (kg CO2 biogenic per unit);
                  None for TBC or non-applicable factors.
    """
    val_sql = "NULL" if value is None else str(value)
    bio_sql = "NULL" if biogenic is None else str(biogenic)
    op.execute(
        _INSERT_FACTOR.format(
            factor_id=factor_id,
            version=version,
            substance=substance,
            scope=scope,
            category=category,
            source=source,
            value=val_sql,
            is_licence_only=str(is_licence_only).upper(),
            is_tbc=str(is_tbc).upper(),
            biogenic=bio_sql,
            unit=unit,
            gwp_set=gwp_set,
            vintage=vintage,
            valid_from="2026-05-13",
            note=note,
        )
    )


def upgrade() -> None:
    """Insert 38 factor catalog entries from methodology_validation.md §11."""

    # -- Scope 2 LB / MB -----------------------------------------------------
    _insert(
        "LB_IT_GRID_ISPRA_2024",
        "Electricity grid Italy LB",
        2, "LB", "ISPRA", "Rapporto_413_2025",
        None, "kg CO2 / kWh", "AR6", "2024",
        "Italian grid LB consumption-side; ISPRA Rapporto 413/2025 (2023 data); "
        "2024 vintage pending mid-2026 publication — use 2023 value with offset disclosed.",
        is_tbc=True,
    )
    _insert(
        "MB_IT_RESIDUAL_AIB_2024",
        "Electricity Italian residual mix MB",
        2, "MB-residual", "AIB", "2024",
        None, "kg CO2e / kWh", "AR6", "2024",
        "AIB European Residual Mix 2024 (published 2025-05-30); "
        "numeric value to be retrieved manually from AIB PDF (HTTP 403 in Phase 2 pass); "
        "MG-15 gate.",
        is_tbc=True,
    )
    _insert(
        "MB_GO_ZERO",
        "GO-certified electricity MB",
        2, "MB-GO", "GHGProtocol", "2015",
        0.0, "kg CO2e / kWh", "n/a", "n/a",
        "Applied only after per-certificate QC1-QC8 validation per methodology_validation §2.4; "
        "MG-03 / CG-08 gate.",
    )

    # -- Scope 1 combustion factors (DEFRA 2025) — values TBC pending pinning -
    _insert(
        "COMB_GAS_NAT_CO2_DEFRA_2025",
        "Natural gas combustion — CO2",
        1, "combustion", "DEFRA", "2025",
        None, "kg CO2 / Sm3", "AR6", "2025",
        "DEFRA 2025 natural gas stationary combustion CO2 component; TBC at Phase 5.",
        is_tbc=True,
    )
    _insert(
        "COMB_GAS_NAT_CH4_DEFRA_2025",
        "Natural gas combustion — CH4",
        1, "combustion", "DEFRA", "2025",
        None, "kg CH4 / Sm3", "AR6", "2025",
        "DEFRA 2025 natural gas CH4 component; TBC at Phase 5.",
        is_tbc=True,
    )
    _insert(
        "COMB_GAS_NAT_N2O_DEFRA_2025",
        "Natural gas combustion — N2O",
        1, "combustion", "DEFRA", "2025",
        None, "kg N2O / Sm3", "AR6", "2025",
        "DEFRA 2025 natural gas N2O component; TBC at Phase 5.",
        is_tbc=True,
    )
    _insert(
        "COMB_GASOLIO_CO2_DEFRA_2025",
        "Diesel combustion — CO2",
        1, "combustion", "DEFRA", "2025",
        None, "kg CO2 / litre", "AR6", "2025",
        "DEFRA 2025 diesel (gas oil) mobile combustion CO2; TBC.",
        is_tbc=True,
    )
    _insert(
        "COMB_GASOLIO_CH4_DEFRA_2025",
        "Diesel combustion — CH4",
        1, "combustion", "DEFRA", "2025",
        None, "kg CH4 / litre", "AR6", "2025",
        "DEFRA 2025 diesel CH4; TBC.",
        is_tbc=True,
    )
    _insert(
        "COMB_GASOLIO_N2O_DEFRA_2025",
        "Diesel combustion — N2O",
        1, "combustion", "DEFRA", "2025",
        None, "kg N2O / litre", "AR6", "2025",
        "DEFRA 2025 diesel N2O; TBC.",
        is_tbc=True,
    )
    _insert(
        "COMB_BENZINA_CO2_DEFRA_2025",
        "Petrol combustion — CO2",
        1, "combustion", "DEFRA", "2025",
        None, "kg CO2 / litre", "AR6", "2025",
        "DEFRA 2025 petrol mobile combustion CO2; TBC. SASSUOLO only.",
        is_tbc=True,
    )
    _insert(
        "COMB_BENZINA_CH4_DEFRA_2025",
        "Petrol combustion — CH4",
        1, "combustion", "DEFRA", "2025",
        None, "kg CH4 / litre", "AR6", "2025",
        "DEFRA 2025 petrol CH4; TBC.",
        is_tbc=True,
    )
    _insert(
        "COMB_BENZINA_N2O_DEFRA_2025",
        "Petrol combustion — N2O",
        1, "combustion", "DEFRA", "2025",
        None, "kg N2O / litre", "AR6", "2025",
        "DEFRA 2025 petrol N2O; TBC.",
        is_tbc=True,
    )

    # -- Scope 1 process factor (DETERMINISTIC — IPCC stoichiometric) --------
    _insert(
        "STOICH_CACO3_IPCC_2006",
        "CaCO3 decarbonation — CO2 only",
        1, "process", "IPCC", "2006",
        0.4397, "t CO2 / t CaCO3", "n/a", "n/a",
        "IPCC 2006 Guidelines V3 Ch.2 §2.5.1.3 Table 2.1; chemistry-based, invariant. "
        "IANO Processo_Decarb only; CO2 only (no CH4, no N2O). "
        "Calcination fraction F=1 assumed for gres porcellanato firing at ~1200C.",
    )

    # -- Scope 3 WTT factors (DEFRA 2025) ------------------------------------
    _insert(
        "WTT_GAS_NAT_DEFRA_2025",
        "WTT natural gas",
        3, "Cat 3a", "DEFRA", "2025",
        None, "kg CO2e / Sm3", "AR6", "2025",
        "DEFRA 2025 WTT natural gas; apply to Sigma Scope 1 GAS_NAT per FR-11; TBC.",
        is_tbc=True,
    )
    _insert(
        "WTT_GASOLIO_DEFRA_2025",
        "WTT diesel",
        3, "Cat 3a", "DEFRA", "2025",
        None, "kg CO2e / litre", "AR6", "2025",
        "DEFRA 2025 WTT diesel; apply to Sigma Scope 1 GASOLIO per FR-11; TBC.",
        is_tbc=True,
    )
    _insert(
        "WTT_BENZINA_DEFRA_2025",
        "WTT petrol",
        3, "Cat 3a", "DEFRA", "2025",
        None, "kg CO2e / litre", "AR6", "2025",
        "DEFRA 2025 WTT petrol; SASSUOLO only; TBC.",
        is_tbc=True,
    )
    _insert(
        "WTT_ELEC_DEFRA_2025",
        "WTT electricity (generation upstream)",
        3, "Cat 3b", "DEFRA", "2025",
        None, "kg CO2e / kWh", "AR6", "2025",
        "DEFRA 2025 WTT electricity; apply to total kWh LB basis; TBC.",
        is_tbc=True,
    )
    _insert(
        "TND_ELEC_IT_DEFRA_2025",
        "T&D losses electricity",
        3, "Cat 3c", "DEFRA", "2025",
        None, "kg CO2e / kWh", "AR6", "2025",
        "DEFRA 2025 T&D losses; Italian-specific loss rate (~6.5% Terna) preferred; TBC.",
        is_tbc=True,
    )

    # -- Freight and transport factors (DEFRA 2025) ---------------------------
    _insert(
        "FREIGHT_HGV_DEFRA_2025",
        "Road freight HGV >17t average laden",
        3, "Cat 4", "DEFRA", "2025",
        None, "kg CO2e / tkm", "AR6", "2025",
        "DEFRA 2025 HGV freight; Cat 4 inbound + Cat 9 Italia/Europa road; TBC.",
        is_tbc=True,
    )
    _insert(
        "FREIGHT_RAIL_DEFRA_2025",
        "Freight train",
        3, "Cat 4", "DEFRA", "2025",
        None, "kg CO2e / tkm", "AR6", "2025",
        "DEFRA 2025 freight rail; Feldspati_Treno / Sabbie_Treno (zero-tkm rows produce 0); TBC.",
        is_tbc=True,
    )
    _insert(
        "FREIGHT_SEA_DEFRA_2025",
        "Bulk carrier transoceanic sea",
        3, "Cat 4", "DEFRA", "2025",
        None, "kg CO2e / tkm", "AR6", "2025",
        "DEFRA 2025 sea freight; Cat 4 sea + Cat 9 Export_Nave; TBC.",
        is_tbc=True,
    )

    # -- Business travel (DEFRA 2025 — spend-based) --------------------------
    _insert(
        "TRAVEL_SPEND_FLIGHTS_DEFRA_2025",
        "Business flights spend-based",
        3, "Cat 6", "DEFRA", "2025",
        None, "kg CO2e / GBP", "AR6", "2025",
        "DEFRA 2025 spend-based flights; convert EUR via PPP-adjusted EUR/GBP; TBC.",
        is_tbc=True,
    )
    _insert(
        "TRAVEL_SPEND_HIRECAR_DEFRA_2025",
        "Rental car spend-based",
        3, "Cat 6", "DEFRA", "2025",
        None, "kg CO2e / GBP", "AR6", "2025",
        "DEFRA 2025 hire car spend; convert EUR; TBC.",
        is_tbc=True,
    )
    _insert(
        "TRAVEL_SPEND_HOTEL_DEFRA_2025",
        "Hotel stays spend-based",
        3, "Cat 6", "DEFRA", "2025",
        None, "kg CO2e / GBP", "AR6", "2025",
        "DEFRA 2025 hotel spend; convert EUR; TBC.",
        is_tbc=True,
    )

    # -- Commuting (DEFRA 2025) -----------------------------------------------
    _insert(
        "COMMUTE_CAR_DEFRA_2025",
        "Average car distance-based",
        3, "Cat 7", "DEFRA", "2025",
        None, "kg CO2e / km", "AR6", "2025",
        "DEFRA 2025 average car; 4452800 km 2024 / 4259200 km 2025; FTE 506/484 confirmed; TBC.",
        is_tbc=True,
    )

    # -- Waste (DEFRA 2025) --------------------------------------------------
    _insert(
        "WASTE_LANDFILL_PERIC_DEFRA_2025",
        "Landfill hazardous waste",
        3, "Cat 5", "DEFRA", "2025",
        None, "kg CO2e / tonne", "AR6", "2025",
        "DEFRA 2025 hazardous waste landfill; Cat 5 pericolosi discarica; TBC.",
        is_tbc=True,
    )
    _insert(
        "WASTE_LANDFILL_NONPERIC_DEFRA_2025",
        "Landfill non-hazardous waste",
        3, "Cat 5", "DEFRA", "2025",
        None, "kg CO2e / tonne", "AR6", "2025",
        "DEFRA 2025 non-hazardous landfill; Cat 5; TBC.",
        is_tbc=True,
    )
    _insert(
        "WASTE_RECYCLE_PERIC_DEFRA_2025",
        "Recycling hazardous waste",
        3, "Cat 5", "DEFRA", "2025",
        None, "kg CO2e / tonne", "AR6", "2025",
        "DEFRA 2025 hazardous recycling; cut-off; no avoided-emissions credit; TBC.",
        is_tbc=True,
    )
    _insert(
        "WASTE_RECYCLE_NONPERIC_DEFRA_2025",
        "Recycling non-hazardous waste",
        3, "Cat 5", "DEFRA", "2025",
        None, "kg CO2e / tonne", "AR6", "2025",
        "DEFRA 2025 non-hazardous recycling; cut-off; TBC.",
        is_tbc=True,
    )

    # -- ecoinvent v3.10 — Scope 3 Cat 1 materials (LICENCE-restricted) ------
    _insert(
        "ECOINV_CLAY_V3_10", "Argille (clay at mine)",
        3, "Cat 1", "ecoinvent", "3.10", None, "kg CO2e / kg", "AR6", "n/a",
        "ecoinvent v3.10 clay; mass-based Cat 1; licence-restricted value.", is_licence_only=True,
    )
    _insert(
        "ECOINV_FELDSPAR_V3_10", "Feldspati (feldspar at plant)",
        3, "Cat 1", "ecoinvent", "3.10", None, "kg CO2e / kg", "AR6", "n/a",
        "ecoinvent v3.10 feldspar; mass-based Cat 1; licence-restricted.", is_licence_only=True,
    )
    _insert(
        "ECOINV_SILICA_V3_10", "Sabbie silicee (silica sand at plant)",
        3, "Cat 1", "ecoinvent", "3.10", None, "kg CO2e / kg", "AR6", "n/a",
        "ecoinvent v3.10 silica sand; mass-based Cat 1; licence-restricted.", is_licence_only=True,
    )
    _insert(
        "ECOINV_FRIT_V3_10", "Fritte/smalti",
        3, "Cat 1", "ecoinvent", "3.10", None, "kg CO2e / kg", "AR6", "n/a",
        "ecoinvent v3.10 frit; high uncertainty — flag in DQ-WARN-03; licence-restricted.",
        is_licence_only=True,
    )
    _insert(
        "ECOINV_PIGMENT_V3_10", "Pigmenti (pigment inorganic)",
        3, "Cat 1", "ecoinvent", "3.10", None, "kg CO2e / kg", "AR6", "n/a",
        "ecoinvent v3.10 inorganic pigment; high specific impact; licence-restricted.",
        is_licence_only=True,
    )
    _insert(
        "ECOINV_ADDITIVES_V3_10", "Additivi chimici",
        3, "Cat 1", "ecoinvent", "3.10", None, "kg CO2e / kg", "AR6", "n/a",
        "ecoinvent v3.10 chemical additives; licence-restricted.", is_licence_only=True,
    )
    # ADR-007: biogenic companion fields for cardboard and pallets
    _insert(
        "ECOINV_CARDBOARD_V3_10", "Imballaggi cartone",
        3, "Cat 1", "ecoinvent", "3.10", None, "kg CO2e / kg", "AR6", "n/a",
        "ecoinvent v3.10 corrugated board; biogenic_co2_kg_per_unit is TBC pending licence "
        "retrieval at Phase 5 (OI-9 / ADR-007); fossil + biogenic flows must be split.",
        is_licence_only=True, is_tbc=True, biogenic=None,
    )
    _insert(
        "ECOINV_PALLET_V3_10", "Pallet legno",
        3, "Cat 1", "ecoinvent", "3.10", None, "kg CO2e / kg", "AR6", "n/a",
        "ecoinvent v3.10 EUR-flat pallet; biogenic_co2_kg_per_unit TBC (OI-9 / ADR-007).",
        is_licence_only=True, is_tbc=True, biogenic=None,
    )
    _insert(
        "ECOINV_LDPE_V3_10", "Film plastico (LDPE film)",
        3, "Cat 1", "ecoinvent", "3.10", None, "kg CO2e / kg", "AR6", "n/a",
        "ecoinvent v3.10 LDPE packaging film; licence-restricted.", is_licence_only=True,
    )
    _insert(
        "ECOINV_PP_V3_10", "Reggette PP",
        3, "Cat 1", "ecoinvent", "3.10", None, "kg CO2e / kg", "AR6", "n/a",
        "ecoinvent v3.10 PP strap; licence-restricted.", is_licence_only=True,
    )

    # -- EXIOBASE spend-based (LICENCE-restricted) ----------------------------
    _insert(
        "EXIO_SERVICES_NACE_M", "Servizi vari (professional services)",
        3, "Cat 1", "EXIOBASE", "3.x", None, "kg CO2e / EUR", "AR6", "2024-best",
        "EXIOBASE 3.x NACE M professional services; spend-based Cat 1; licence-restricted.",
        is_licence_only=True,
    )
    _insert(
        "EXIO_MACHINERY_NACE_C28", "Impiantistica",
        3, "Cat 2", "EXIOBASE", "3.x", None, "kg CO2e / EUR", "AR6", "2024-best",
        "EXIOBASE 3.x NACE C.28 machinery; spend-based Cat 2; licence-restricted.",
        is_licence_only=True,
    )
    _insert(
        "EXIO_CONSUMABLES_NACE_C27", "Materiali di consumo",
        3, "Cat 2", "EXIOBASE", "3.x", None, "kg CO2e / EUR", "AR6", "2024-best",
        "EXIOBASE 3.x NACE C.27 electrical equipment; spend-based Cat 2; licence-restricted.",
        is_licence_only=True,
    )

    # -- End-of-life (ecoinvent v3.10 — LICENCE-restricted) ------------------
    _insert(
        "ECOINV_LANDFILL_INERT_V3_10", "Tiles end-of-life landfill (inert)",
        3, "Cat 12", "ecoinvent", "3.10", None, "kg CO2e / kg", "AR6", "n/a",
        "ecoinvent v3.10 inert landfill; 30% split per FR-17; cut-off; licence-restricted.",
        is_licence_only=True,
    )
    _insert(
        "ECOINV_CDW_RECYCLE_V3_10", "Tiles end-of-life construction-waste recycling",
        3, "Cat 12", "ecoinvent", "3.10", None, "kg CO2e / kg", "AR6", "n/a",
        "ecoinvent v3.10 CDW recycling; 70% split per FR-17; cut-off; licence-restricted.",
        is_licence_only=True,
    )


def downgrade() -> None:
    """Remove all factor catalog seed rows inserted by M2."""
    factor_ids = [
        "LB_IT_GRID_ISPRA_2024", "MB_IT_RESIDUAL_AIB_2024", "MB_GO_ZERO",
        "COMB_GAS_NAT_CO2_DEFRA_2025", "COMB_GAS_NAT_CH4_DEFRA_2025",
        "COMB_GAS_NAT_N2O_DEFRA_2025", "COMB_GASOLIO_CO2_DEFRA_2025",
        "COMB_GASOLIO_CH4_DEFRA_2025", "COMB_GASOLIO_N2O_DEFRA_2025",
        "COMB_BENZINA_CO2_DEFRA_2025", "COMB_BENZINA_CH4_DEFRA_2025",
        "COMB_BENZINA_N2O_DEFRA_2025", "STOICH_CACO3_IPCC_2006",
        "WTT_GAS_NAT_DEFRA_2025", "WTT_GASOLIO_DEFRA_2025", "WTT_BENZINA_DEFRA_2025",
        "WTT_ELEC_DEFRA_2025", "TND_ELEC_IT_DEFRA_2025",
        "FREIGHT_HGV_DEFRA_2025", "FREIGHT_RAIL_DEFRA_2025", "FREIGHT_SEA_DEFRA_2025",
        "TRAVEL_SPEND_FLIGHTS_DEFRA_2025", "TRAVEL_SPEND_HIRECAR_DEFRA_2025",
        "TRAVEL_SPEND_HOTEL_DEFRA_2025", "COMMUTE_CAR_DEFRA_2025",
        "WASTE_LANDFILL_PERIC_DEFRA_2025", "WASTE_LANDFILL_NONPERIC_DEFRA_2025",
        "WASTE_RECYCLE_PERIC_DEFRA_2025", "WASTE_RECYCLE_NONPERIC_DEFRA_2025",
        "ECOINV_CLAY_V3_10", "ECOINV_FELDSPAR_V3_10", "ECOINV_SILICA_V3_10",
        "ECOINV_FRIT_V3_10", "ECOINV_PIGMENT_V3_10", "ECOINV_ADDITIVES_V3_10",
        "ECOINV_CARDBOARD_V3_10", "ECOINV_PALLET_V3_10",
        "ECOINV_LDPE_V3_10", "ECOINV_PP_V3_10",
        "EXIO_SERVICES_NACE_M", "EXIO_MACHINERY_NACE_C28", "EXIO_CONSUMABLES_NACE_C27",
        "ECOINV_LANDFILL_INERT_V3_10", "ECOINV_CDW_RECYCLE_V3_10",
    ]
    ids_sql = ", ".join(f"'{fid}'" for fid in factor_ids)
    op.execute(f"DELETE FROM ref.factor_catalog WHERE factor_id IN ({ids_sql});")

"""M8 — NCV dual-unit factor variants for combustion Scope 1 (DEFRA 2024).

Implements decision #3 from auto_calc_design.md §12:
  "Per ogni fuel pubblicare entrambe le varianti factor dove la fonte
   autorevole le pubblica."

Adds:
  - DEFRA 2024 base combustion factors (per-Sm3 / per-litre) for GAS_NAT,
    GASOLIO_AUTO, and BENZINA_AUTO — CO2, CH4, N2O components each.
  - Derived per-kWh variants for CO2 components (CH4/N2O are typically
    given per-Sm3 or per-litre; the kWh variant is used for invoice
    matching when energy billing is in kWh).
  - NCV references (DEFRA 2024 GHG Conversion Factors v1.0, validated
    against IPCC 2006 Vol.2 Ch.1 and GHG Protocol EF guide):
      Gas naturale : 9.59 kWh/Sm³  (@ 15°C, 1 atm, dry basis)
      Gasolio auto : 9.97 kWh/L    (density 0.832 kg/L × 42.7 MJ/kg NCV)
      Benzina auto : 9.20 kWh/L    (density 0.741 kg/L × 44.7 MJ/kg NCV)

DEFRA 2024 v1.0 source values used here
(Greenhouse Gas Reporting: Conversion Factors 2024, DESNZ/DBET, June 2024):
  GAS_NAT  CO2 : 2.02233  kg CO2 / Sm3   (stationary combustion, gross CV basis)
  GAS_NAT  CH4 : 0.000038 kg CH4 / Sm3
  GAS_NAT  N2O : 0.000006 kg N2O / Sm3
  GASOLIO  CO2 : 2.51614  kg CO2 / litre  (diesel for transport/mobile)
  GASOLIO  CH4 : 0.000055 kg CH4 / litre
  GASOLIO  N2O : 0.000147 kg N2O / litre
  BENZINA  CO2 : 2.16845  kg CO2 / litre  (petrol for transport/mobile)
  BENZINA  CH4 : 0.000081 kg CH4 / litre
  BENZINA  N2O : 0.000147 kg N2O / litre

Derived per-kWh CO2 values:
  GAS_NAT  CO2 / kWh = 2.02233  / 9.59  = 0.210878 kg CO2 / kWh
  GASOLIO  CO2 / kWh = 2.51614  / 9.97  = 0.252371 kg CO2 / kWh
  BENZINA  CO2 / kWh = 2.16845  / 9.20  = 0.235701 kg CO2 / kWh

Mathematical relation:
  factor_per_kwh = factor_per_native_unit / NCV_kwh_per_native_unit
  tolerance check: factor_per_kwh * NCV == factor_per_native_unit ± 0.1%

Revision ID : 0028_M8
Revises     : 0026_M6
Create Date : 2026-05-15
"""

from __future__ import annotations

from alembic import op

# ---------------------------------------------------------------------------
revision: str = "0028_M8"
down_revision: str = "0026_M6"
branch_labels: str | None = None
depends_on: str | None = None
# ---------------------------------------------------------------------------

# NCV constants — DEFRA 2024 GHG Conversion Factors v1.0
_NCV_GAS_NAT_KWH_PER_SM3: float = 9.59   # kWh/Sm³ @ 15°C 1 atm
_NCV_GASOLIO_KWH_PER_L: float = 9.97     # kWh/L
_NCV_BENZINA_KWH_PER_L: float = 9.20     # kWh/L

# ---------------------------------------------------------------------------
# SQL template (mirrors 0003_M2 pattern for consistency)
# ---------------------------------------------------------------------------
_INSERT_FACTOR = """
INSERT INTO ref.factor_catalog
    (tenant_id, factor_id, version, substance, scope, category, source,
     value, is_licence_only, is_tbc, biogenic_co2_kg_per_unit,
     unit, gwp_set, vintage, valid_from, applicability_note,
     published_by, published_at, is_published)
SELECT t.id,
    {factor_id!r}, {version!r}, {substance!r}, {scope}, {category!r}, {source!r},
    {value}, FALSE, FALSE, NULL,
    {unit!r}, {gwp_set!r}, {vintage!r}, {valid_from!r}, {note!r},
    'system_seed', now(), TRUE
FROM ref.tenants t WHERE t.code = 'CERAMIC_TILE_CO';
"""


def _insert(
    factor_id: str,
    substance: str,
    scope: int,
    category: str,
    source: str,
    version: str,
    value: float,
    unit: str,
    gwp_set: str,
    vintage: str,
    note: str,
) -> None:
    """Execute a single factor catalog INSERT (published immediately).

    Args:
        factor_id: Unique factor identifier.
        substance: Human-readable substance or activity description.
        scope: GHG scope (1, 2, or 3).
        category: Factor category label.
        source: Authoritative source code.
        version: Source version string.
        value: Confirmed numeric emission factor value (never NULL here).
        unit: Emission factor unit string.
        gwp_set: GWP set identifier.
        vintage: Factor vintage year.
        note: Applicability note.
    """
    op.execute(
        _INSERT_FACTOR.format(
            factor_id=factor_id,
            version=version,
            substance=substance,
            scope=scope,
            category=category,
            source=source,
            value=str(value),
            unit=unit,
            gwp_set=gwp_set,
            vintage=vintage,
            valid_from="2026-05-15",
            note=note,
        )
    )


# ---------------------------------------------------------------------------
# Utility: NCV-derived value with round-trip comment
# ---------------------------------------------------------------------------
def _ncv_derived(native_value: float, ncv: float) -> float:
    """Return per-kWh factor = native_value / ncv, rounded to 6 decimal places."""
    return round(native_value / ncv, 6)


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    """Insert DEFRA 2024 base + NCV-derived per-kWh combustion factors."""

    source = "DEFRA"
    version = "2024_v1.0"
    vintage = "2024"
    gwp = "AR6"
    scope = 1
    cat = "combustion"
    citation = "DEFRA 2024 GHG Conversion Factors v1.0 (derived via NCV)"

    # -----------------------------------------------------------------------
    # GAS NATURALE — base per Sm3
    # -----------------------------------------------------------------------
    _insert(
        "COMB_GAS_NAT_CO2_DEFRA_2024_PER_SM3",
        "Natural gas combustion — CO2 (per Sm3)",
        scope, cat, source, version,
        2.02233,
        "kg CO2 / Sm3",
        gwp, vintage,
        "DEFRA 2024 v1.0 natural gas stationary combustion CO2; "
        "gross CV basis; source: Greenhouse Gas Reporting Conversion Factors 2024 "
        "DESNZ/DBET Table 1a; AR6 GWPs.",
    )
    _insert(
        "COMB_GAS_NAT_CH4_DEFRA_2024_PER_SM3",
        "Natural gas combustion — CH4 (per Sm3)",
        scope, cat, source, version,
        0.000038,
        "kg CH4 / Sm3",
        gwp, vintage,
        "DEFRA 2024 v1.0 natural gas stationary combustion CH4 component; AR6 GWPs.",
    )
    _insert(
        "COMB_GAS_NAT_N2O_DEFRA_2024_PER_SM3",
        "Natural gas combustion — N2O (per Sm3)",
        scope, cat, source, version,
        0.000006,
        "kg N2O / Sm3",
        gwp, vintage,
        "DEFRA 2024 v1.0 natural gas stationary combustion N2O component; AR6 GWPs.",
    )

    # GAS NATURALE — derived per kWh (NCV = 9.59 kWh/Sm3)
    _gas_co2_kwh = _ncv_derived(2.02233, _NCV_GAS_NAT_KWH_PER_SM3)
    _insert(
        "COMB_GAS_NAT_CO2_DEFRA_2024_PER_KWH",
        "Natural gas combustion — CO2 (per kWh, NCV derived)",
        scope, cat, source, version,
        _gas_co2_kwh,
        "kg CO2 / kWh",
        gwp, vintage,
        f"{citation}; "
        f"derived_from_COMB_GAS_NAT_CO2_DEFRA_2024_PER_SM3_via_ncv; "
        f"NCV gas naturale = {_NCV_GAS_NAT_KWH_PER_SM3} kWh/Sm3 "
        f"(DEFRA 2024 NCV table, IPCC 2006 Vol.2 Ch.1); "
        f"value = 2.02233 / {_NCV_GAS_NAT_KWH_PER_SM3} = {_gas_co2_kwh} kg CO2/kWh.",
    )

    # -----------------------------------------------------------------------
    # GASOLIO AUTO — base per litre
    # -----------------------------------------------------------------------
    _insert(
        "COMB_GASOLIO_AUTO_CO2_DEFRA_2024_PER_LITER",
        "Diesel auto combustion — CO2 (per litre)",
        scope, cat, source, version,
        2.51614,
        "kg CO2 / litre",
        gwp, vintage,
        "DEFRA 2024 v1.0 diesel (gas oil) mobile combustion CO2; "
        "source: DESNZ/DBET Table 3a; AR6 GWPs.",
    )
    _insert(
        "COMB_GASOLIO_AUTO_CH4_DEFRA_2024_PER_LITER",
        "Diesel auto combustion — CH4 (per litre)",
        scope, cat, source, version,
        0.000055,
        "kg CH4 / litre",
        gwp, vintage,
        "DEFRA 2024 v1.0 diesel mobile combustion CH4 component; AR6 GWPs.",
    )
    _insert(
        "COMB_GASOLIO_AUTO_N2O_DEFRA_2024_PER_LITER",
        "Diesel auto combustion — N2O (per litre)",
        scope, cat, source, version,
        0.000147,
        "kg N2O / litre",
        gwp, vintage,
        "DEFRA 2024 v1.0 diesel mobile combustion N2O component; AR6 GWPs.",
    )

    # GASOLIO AUTO — derived per kWh (NCV = 9.97 kWh/L)
    _gasolio_co2_kwh = _ncv_derived(2.51614, _NCV_GASOLIO_KWH_PER_L)
    _insert(
        "COMB_GASOLIO_AUTO_CO2_DEFRA_2024_PER_KWH",
        "Diesel auto combustion — CO2 (per kWh, NCV derived)",
        scope, cat, source, version,
        _gasolio_co2_kwh,
        "kg CO2 / kWh",
        gwp, vintage,
        f"{citation}; "
        f"derived_from_COMB_GASOLIO_AUTO_CO2_DEFRA_2024_PER_LITER_via_ncv; "
        f"NCV gasolio auto = {_NCV_GASOLIO_KWH_PER_L} kWh/L "
        f"(density 0.832 kg/L x 42.7 MJ/kg NCV; GHG Protocol EF guide + IPCC 2006 Vol.2 Ch.1); "
        f"value = 2.51614 / {_NCV_GASOLIO_KWH_PER_L} = {_gasolio_co2_kwh} kg CO2/kWh.",
    )

    # -----------------------------------------------------------------------
    # BENZINA AUTO — base per litre
    # -----------------------------------------------------------------------
    _insert(
        "COMB_BENZINA_AUTO_CO2_DEFRA_2024_PER_LITER",
        "Petrol auto combustion — CO2 (per litre)",
        scope, cat, source, version,
        2.16845,
        "kg CO2 / litre",
        gwp, vintage,
        "DEFRA 2024 v1.0 petrol (motor gasoline) mobile combustion CO2; "
        "source: DESNZ/DBET Table 3a; AR6 GWPs.",
    )
    _insert(
        "COMB_BENZINA_AUTO_CH4_DEFRA_2024_PER_LITER",
        "Petrol auto combustion — CH4 (per litre)",
        scope, cat, source, version,
        0.000081,
        "kg CH4 / litre",
        gwp, vintage,
        "DEFRA 2024 v1.0 petrol mobile combustion CH4 component; AR6 GWPs.",
    )
    _insert(
        "COMB_BENZINA_AUTO_N2O_DEFRA_2024_PER_LITER",
        "Petrol auto combustion — N2O (per litre)",
        scope, cat, source, version,
        0.000147,
        "kg N2O / litre",
        gwp, vintage,
        "DEFRA 2024 v1.0 petrol mobile combustion N2O component; AR6 GWPs.",
    )

    # BENZINA AUTO — derived per kWh (NCV = 9.20 kWh/L)
    _benzina_co2_kwh = _ncv_derived(2.16845, _NCV_BENZINA_KWH_PER_L)
    _insert(
        "COMB_BENZINA_AUTO_CO2_DEFRA_2024_PER_KWH",
        "Petrol auto combustion — CO2 (per kWh, NCV derived)",
        scope, cat, source, version,
        _benzina_co2_kwh,
        "kg CO2 / kWh",
        gwp, vintage,
        f"{citation}; "
        f"derived_from_COMB_BENZINA_AUTO_CO2_DEFRA_2024_PER_LITER_via_ncv; "
        f"NCV benzina auto = {_NCV_BENZINA_KWH_PER_L} kWh/L "
        f"(density 0.741 kg/L x 44.7 MJ/kg NCV; GHG Protocol EF guide + IPCC 2006 Vol.2 Ch.1); "
        f"value = 2.16845 / {_NCV_BENZINA_KWH_PER_L} = {_benzina_co2_kwh} kg CO2/kWh.",
    )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    """Remove all factor catalog rows inserted by M8."""
    factor_ids = [
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
    ids_sql = ", ".join(f"'{fid}'" for fid in factor_ids)
    op.execute(
        f"DELETE FROM ref.factor_catalog WHERE factor_id IN ({ids_sql}) "
        f"AND version = '2024_v1.0';"
    )

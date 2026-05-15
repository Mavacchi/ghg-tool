"""Auto-calc service: single-row quantity × factor → tCO2e.

Implements the compute_preview / compute_and_insert pair described in
auto_calc_design.md §10. Every sub-scope delegates to the existing
application/calc/* modules — no GHG logic is duplicated here.

Sub-handler count: 13
  S1: combustion, process-Mode-A (direct_tco2), process-Mode-B (caco3_mass)
  S2: lb, mb
  S3: cat1, cat3, cat4, cat5, cat6, cat7, cat9, cat12

Vintage selection: delegated to FactorCatalogPort.get(vintage_year=anno)
which implements closest-prior in the SQL adapter (ORDER BY valid_from DESC
with vintage <= anno constraint). The service passes `anno` as the vintage
hint so the adapter applies Option B closest-prior automatically.

Unit conversions (§4 hybrid rules):
  Dimension-preserving exact only:
    kWh ↔ MWh  (×1000 / ÷1000)
    t   ↔ kg   (×1000 / ÷1000)
    l   ↔ m3   (×1000 / ÷1000)
  NCV-dependent conversions (e.g. Sm3→kWh) are REJECTED with
  UnitConversionError (422 at router level).

Decimal precision: Decimal everywhere; never float for calc numerics.

M6 additions (auto_calc_design.md §12 second round):
  Task B: validate site_type == 'STABILIMENTO_PRODUTTIVO' before dispatching
    to _handle_s1_process; raise HTTPException 422 otherwise.
  Task C: resolve country from ref.sites for S2 LB factor lookup instead of
    hardcoding 'IT'.
  Task D: on compute_and_insert, also insert into raw.direct_entry and link
    raw_row_id on the emissions_consolidated row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import structlog
from fastapi import HTTPException, status

from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.schemas.calc_schemas import (
    CalcInputRequest,
    CalcInsertResponse,
    CalcPreviewResponse,
)
from ghg_tool.application.calc._helpers import KG_TO_TONNE, require_factor
from ghg_tool.domain.exceptions.calc_errors import MissingFactorError
from ghg_tool.domain.ports.factor_catalog import FactorCatalogPort

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class UnitConversionError(ValueError):
    """Raised when a requested unit conversion requires NCV or other
    non-dimension-preserving context (e.g. Sm3 → kWh for gas).
    Surfaces as HTTP 422 at the router level.
    """


# ---------------------------------------------------------------------------
# Site metadata dataclass (loaded on-demand for site-aware logic)
# ---------------------------------------------------------------------------

from dataclasses import dataclass  # noqa: E402 (imported here for grouping clarity)


@dataclass(frozen=True)
class _SiteMeta:
    """Minimal site attributes retrieved from ref.sites for per-request logic.

    Attributes:
        codice_sito: Site code primary key.
        site_type: STABILIMENTO_PRODUTTIVO | UFFICIO | MAGAZZINO
        country: ISO-3166 alpha-2 country code (default 'IT').
    """

    codice_sito: str
    site_type: str
    country: str


async def _fetch_site_meta(
    session: Any,
    *,
    codice_sito: str,
    tenant_id: str,
) -> _SiteMeta | None:
    """Query ref.sites for site_type and country given a codice_sito.

    Returns None if no active site row matches (caller decides error handling).

    Args:
        session: Async SQLAlchemy session.
        codice_sito: Site code to look up.
        tenant_id: UUID string of the tenant (RLS pre-filtered but we also
            pass it explicitly for defence-in-depth).

    Returns:
        _SiteMeta if found; None otherwise.
    """
    from sqlalchemy import text  # noqa: PLC0415

    result = await session.execute(
        text(
            "SELECT codice_sito, site_type, country "
            "FROM ref.sites "
            "WHERE codice_sito = :codice_sito "
            "  AND tenant_id = CAST(:tenant_id AS uuid) "
            "  AND is_active = TRUE "
            "LIMIT 1"
        ),
        {"codice_sito": codice_sito, "tenant_id": tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return _SiteMeta(
        codice_sito=str(row["codice_sito"]),
        site_type=str(row["site_type"]),
        country=str(row["country"]),
    )


def _assert_process_site_type(
    codice_sito: str,
    site_type: str,
) -> None:
    """Raise HTTPException 422 if site_type != 'STABILIMENTO_PRODUTTIVO'.

    Decision #7 from auto_calc_design.md §12: Processo_Decarb is only
    applicable to STABILIMENTO_PRODUTTIVO sites.  UFFICIO and MAGAZZINO
    must be rejected at the application layer.

    Args:
        codice_sito: Site code (for error detail).
        site_type: Actual site_type value from ref.sites.

    Raises:
        HTTPException 422 if site_type is not STABILIMENTO_PRODUTTIVO.
    """
    if site_type != "STABILIMENTO_PRODUTTIVO":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "site_type_invalid",
                "message": (
                    "Process emissions allowed only for STABILIMENTO_PRODUTTIVO sites"
                ),
                "codice_sito": codice_sito,
                "site_type": site_type,
            },
        )


# ---------------------------------------------------------------------------
# Dimension-preserving unit conversion table
# Format: (from_unit_normalised, to_unit_normalised) → multiplier
# The factor catalog declares a canonical unit; we convert the *quantity*
# to match the factor's input unit before multiplying.
# ---------------------------------------------------------------------------

_UNIT_CONVERSION: dict[tuple[str, str], Decimal] = {
    # Energy
    ("kwh", "mwh"): Decimal("0.001"),
    ("mwh", "kwh"): Decimal("1000"),
    # Mass
    ("kg", "t"): Decimal("0.001"),
    ("t", "kg"): Decimal("1000"),
    ("kg", "tonne"): Decimal("0.001"),
    ("tonne", "kg"): Decimal("1000"),
    # Volume (liquids only — exact at STP; Sm3 → kWh is NCV-dependent)
    ("l", "m3"): Decimal("0.001"),
    ("m3", "l"): Decimal("1000"),
    ("litri", "m3"): Decimal("0.001"),
    ("m3", "litri"): Decimal("1000"),
    # Identity
    ("kwh", "kwh"): Decimal("1"),
    ("mwh", "mwh"): Decimal("1"),
    ("kg", "kg"): Decimal("1"),
    ("t", "t"): Decimal("1"),
    ("tonne", "tonne"): Decimal("1"),
    ("l", "l"): Decimal("1"),
    ("litri", "litri"): Decimal("1"),
    ("m3", "m3"): Decimal("1"),
    ("sm3", "sm3"): Decimal("1"),
    ("km", "km"): Decimal("1"),
    ("tkm", "tkm"): Decimal("1"),
    ("eur", "eur"): Decimal("1"),
    ("gbp", "gbp"): Decimal("1"),
    ("tco2", "tco2"): Decimal("1"),
    ("tco2e", "tco2e"): Decimal("1"),
}

# Units that require NCV and must never be auto-converted
_NCV_DEPENDENT_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ("sm3", "kwh"), ("kwh", "sm3"),
    ("sm3", "mwh"), ("mwh", "sm3"),
    ("litri", "kwh"), ("kwh", "litri"),
    ("m3", "kwh"), ("kwh", "m3"),
    ("l", "kwh"), ("kwh", "l"),
})


def _apply_unit_conversion(
    quantita: Decimal,
    from_unit: str,
    to_unit: str,
) -> tuple[Decimal, str]:
    """Convert quantity from from_unit to to_unit using exact dimension rules.

    Args:
        quantita: The original quantity.
        from_unit: Unit as supplied in the request.
        to_unit: Target unit expected by the factor catalog.

    Returns:
        Tuple of (converted_quantity, human_description).

    Raises:
        UnitConversionError: If the conversion is NCV-dependent or unknown.
    """
    from_n = from_unit.lower().strip()
    to_n = to_unit.lower().strip()

    if from_n == to_n:
        return quantita, f"{from_unit} -> {to_unit} (no conversion)"

    pair = (from_n, to_n)
    if pair in _NCV_DEPENDENT_PAIRS:
        raise UnitConversionError(
            f"Unit conversion {from_unit!r} -> {to_unit!r} requires NCV "
            "(net calorific value) and is not supported by the "
            "dimension-preserving converter. "
            "Supply the quantity already in the factor's native unit."
        )

    multiplier = _UNIT_CONVERSION.get(pair)
    if multiplier is None:
        raise UnitConversionError(
            f"No dimension-preserving conversion defined from {from_unit!r} to {to_unit!r}. "
            "Supply the quantity in the factor's native unit, or use a supported "
            "conversion (kWh↔MWh, kg↔t, l↔m3)."
        )

    converted = quantita * multiplier
    return converted, f"{quantita} {from_unit} -> {converted} {to_unit} (×{multiplier})"


def _quantize_tco2e(value: Decimal) -> Decimal:
    """Round a tCO2e value to 6 decimal places (Decimal 15,6 per §9).

    Args:
        value: Raw Decimal tCO2e.

    Returns:
        Rounded Decimal to 6dp.
    """
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# S1 sub-handlers
# ---------------------------------------------------------------------------

def _preview_s1_combustion(
    req: CalcInputRequest,
    catalog: FactorCatalogPort,
) -> CalcPreviewResponse:
    """Scope 1 combustion: CO2 + CH4 + N2O via DEFRA factors.

    Reuses the factor IDs from application.calc.scope1_combustion.
    The CO2 factor is the canonical anchor; CH4 and N2O contribute to tco2e.

    Args:
        req: Validated CalcInputRequest.
        catalog: Factor catalog port.

    Returns:
        CalcPreviewResponse with full combustion breakdown.
    """
    from ghg_tool.application.calc.scope1_combustion import _FUEL_FACTOR_IDS
    from ghg_tool.domain.ports.gwp_table import GWPSetTable
    from ghg_tool.domain.value_objects.gwp_set import get_gwp_values

    gwp_values = get_gwp_values(req.gwp_set)
    gwp = GWPSetTable(gwp_values)

    combustibile = req.combustibile  # already validated non-None
    factor_ids = _FUEL_FACTOR_IDS[combustibile]  # type: ignore[index]

    co2_factor = require_factor(
        catalog, factor_ids["CO2"], gwp_set=req.gwp_set, vintage_year=req.anno
    )
    ch4_factor = require_factor(
        catalog, factor_ids["CH4"], gwp_set=req.gwp_set, vintage_year=req.anno
    )
    n2o_factor = require_factor(
        catalog, factor_ids["N2O"], gwp_set=req.gwp_set, vintage_year=req.anno
    )

    quantita = req.quantita

    co2_kg = (co2_factor.value or Decimal("0")) * quantita
    ch4_kg = (ch4_factor.value or Decimal("0")) * quantita
    n2o_kg = (n2o_factor.value or Decimal("0")) * quantita

    co2_tonne = co2_kg * KG_TO_TONNE
    ch4_tco2e = ch4_kg * KG_TO_TONNE * gwp.get("CH4")
    n2o_tco2e = n2o_kg * KG_TO_TONNE * gwp.get("N2O")
    tco2e = _quantize_tco2e(co2_tonne + ch4_tco2e + n2o_tco2e)

    warnings: list[str] = []
    if co2_factor.vintage and str(co2_factor.vintage) != str(req.anno):
        warnings.append(
            f"Vintage {co2_factor.vintage} used (closest-prior to {req.anno} request)"
        )

    co2_v = co2_factor.value or Decimal("0")
    formula = (
        f"{quantita} {req.unita} × {co2_v} kg CO2/{req.unita} × 1e-3 = {co2_tonne} tCO2 "
        f"(+ CH4: {ch4_tco2e} tCO2e + N2O: {n2o_tco2e} tCO2e) = {tco2e} tCO2e"
    )

    return CalcPreviewResponse(
        tco2e=tco2e,
        co2_biogenic_tonne=None,
        co2_fossil_tonne=_quantize_tco2e(co2_tonne),
        factor_id=co2_factor.factor_id,
        factor_value=co2_v,
        factor_unit=co2_factor.unit,
        factor_source=co2_factor.source,
        factor_version=co2_factor.version,
        factor_vintage=str(co2_factor.vintage or req.anno),
        gwp_set=req.gwp_set,
        gwp_value=Decimal("1"),
        methodology="activity-based",
        formula_human=formula,
        unit_conversion_applied=None,
        warnings=warnings,
    )


def _preview_s1_process(
    req: CalcInputRequest,
    catalog: FactorCatalogPort,
) -> CalcPreviewResponse:
    """Scope 1 process emissions (IANO only) — Mode A or Mode B.

    Mode A (direct_tco2, default):
        tco2e = quantita (user supplies already-calculated tCO2 mass)
        factor_source = 'direct_input'

    Mode B (caco3_mass):
        tco2e = quantita × 0.4397 (STOICH_CACO3_IPCC_2006)
        Reuses application.calc.scope1_process factor ID.

    Args:
        req: Validated CalcInputRequest.
        catalog: Factor catalog port.

    Returns:
        CalcPreviewResponse for the selected process mode.
    """
    effective_mode = req.process_mode or "direct_tco2"
    warnings: list[str] = []

    if req.codice_sito and req.codice_sito.upper() != "IANO":
        warnings.append(
            f"S1 process is designed for site IANO; "
            f"codice_sito={req.codice_sito!r} — verify applicability."
        )

    if effective_mode == "direct_tco2":
        # Mode A: quantity IS the tCO2 value
        tco2e = _quantize_tco2e(req.quantita)
        return CalcPreviewResponse(
            tco2e=tco2e,
            co2_biogenic_tonne=None,
            co2_fossil_tonne=None,
            factor_id="DIRECT_TCO2_INPUT",
            factor_value=Decimal("1"),
            factor_unit="tCO2 / tCO2",
            factor_source="direct_input",
            factor_version="n/a",
            factor_vintage="n/a",
            gwp_set=req.gwp_set,
            gwp_value=Decimal("1"),
            methodology="stoichiometric",
            formula_human=(
                f"{req.quantita} tCO2 × 1 (direct input, Mode A) = {tco2e} tCO2e"
            ),
            unit_conversion_applied=None,
            warnings=warnings,
        )

    # Mode B: CaCO3 stoichiometric
    from ghg_tool.application.calc.scope1_process import _FACTOR_ID as STOICH_FACTOR_ID

    factor = require_factor(
        catalog, STOICH_FACTOR_ID, gwp_set=req.gwp_set, vintage_year=req.anno
    )

    # Defence-in-depth: value must be 0.4397 per methodology_validation §6.4
    if factor.value != Decimal("0.4397"):
        raise ValueError(
            f"Stoichiometric factor value mismatch: expected 0.4397, "
            f"got {factor.value!r} for {factor.factor_id}"
        )

    co2_tonne = (factor.value) * req.quantita
    tco2e = _quantize_tco2e(co2_tonne)

    if factor.vintage and str(factor.vintage) != str(req.anno):
        warnings.append(
            f"Vintage {factor.vintage} used (closest-prior to {req.anno} request)"
        )

    return CalcPreviewResponse(
        tco2e=tco2e,
        co2_biogenic_tonne=None,
        co2_fossil_tonne=None,
        factor_id=factor.factor_id,
        factor_value=factor.value,
        factor_unit=factor.unit,
        factor_source=factor.source,
        factor_version=factor.version,
        factor_vintage=str(factor.vintage or req.anno),
        gwp_set=req.gwp_set,
        gwp_value=Decimal("1"),
        methodology="stoichiometric",
        formula_human=(
            f"{req.quantita} t CaCO3 × {factor.value} tCO2/t CaCO3 = {tco2e} tCO2e"
        ),
        unit_conversion_applied=None,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# S2 sub-handlers
# ---------------------------------------------------------------------------

def _preview_s2_lb(
    req: CalcInputRequest,
    catalog: FactorCatalogPort,
    *,
    country: str = "IT",
) -> CalcPreviewResponse:
    """Scope 2 location-based: ISPRA Italian grid factor × kWh.

    Decision #2 (M6): ``country`` is resolved from ``ref.sites`` at the call
    site rather than being hardcoded.  When a non-IT country is requested and
    no matching LB factor exists in the catalog the resolver raises
    ``MissingFactorError`` with a clear message.

    Args:
        req: Validated CalcInputRequest.
        catalog: Factor catalog port.
        country: ISO-3166 alpha-2 country code resolved from ref.sites
            (default 'IT' when session is unavailable, e.g. in tests).

    Returns:
        CalcPreviewResponse for S2 LB.
    """
    from ghg_tool.application.calc.scope2_lb import _LB_FACTOR_ID

    # Build the country-aware factor ID.  The baseline factor is named
    # LB_IT_GRID_ISPRA_2024; for non-IT countries we construct the variant
    # name by substituting the country code and attempt lookup.
    if country == "IT":
        factor_id_to_use = _LB_FACTOR_ID
    else:
        # Non-IT sites: derive the expected factor ID pattern from the IT one.
        # Example: LB_IT_GRID_ISPRA_2024 → LB_DE_GRID_ISPRA_2024 for country=DE.
        factor_id_to_use = _LB_FACTOR_ID.replace("_IT_", f"_{country}_", 1)

    try:
        factor = require_factor(
            catalog, factor_id_to_use, gwp_set=req.gwp_set, vintage_year=req.anno
        )
    except MissingFactorError as exc:
        if country != "IT":
            raise MissingFactorError(
                f"No Location-Based emission factor found for country='{country}'. "
                f"Expected factor_id='{factor_id_to_use}' (gwp_set={req.gwp_set}, "
                f"vintage<={req.anno}). "
                "Add the country-specific LB factor to the factor catalog, "
                "or contact the data steward."
            ) from exc
        raise

    quantita = req.quantita
    unit_desc: str | None = None

    # Factor expects kWh; apply dimension-preserving conversion if needed
    if req.unita.lower() not in ("kwh",):
        quantita, unit_desc = _apply_unit_conversion(req.quantita, req.unita, "kWh")

    tco2e = _quantize_tco2e((factor.value or Decimal("0")) * quantita * KG_TO_TONNE)

    warnings: list[str] = []
    if factor.vintage and str(factor.vintage) != str(req.anno):
        warnings.append(
            f"Vintage {factor.vintage} used (closest-prior to {req.anno} request)"
        )
    if country != "IT":
        warnings.append(
            f"Non-IT site: LB factor resolved for country='{country}' "
            f"(factor_id={factor_id_to_use!r})"
        )

    fv = factor.value or Decimal("0")
    formula = f"{quantita} kWh × {fv} kgCO2/kWh × 1e-3 = {tco2e} tCO2e [LB country={country}]"

    return CalcPreviewResponse(
        tco2e=tco2e,
        co2_biogenic_tonne=None,
        co2_fossil_tonne=None,
        factor_id=factor.factor_id,
        factor_value=fv,
        factor_unit=factor.unit,
        factor_source=factor.source,
        factor_version=factor.version,
        factor_vintage=str(factor.vintage or req.anno),
        gwp_set=req.gwp_set,
        gwp_value=Decimal("1"),
        methodology="location-based",
        formula_human=formula,
        unit_conversion_applied=unit_desc,
        warnings=warnings,
    )


def _preview_s2_mb(
    req: CalcInputRequest,
    catalog: FactorCatalogPort,
) -> CalcPreviewResponse:
    """Scope 2 market-based: GO → 0 factor, PPA/RESIDUAL → Italian AIB residual.

    Mapping from strumento_mb:
        GO       → MB_GO_ZERO (0 tCO2e)
        PPA      → MB_IT_RESIDUAL_AIB_2024 (treated as residual per market rules)
        RESIDUAL → MB_IT_RESIDUAL_AIB_2024

    Args:
        req: Validated CalcInputRequest.
        catalog: Factor catalog port.

    Returns:
        CalcPreviewResponse for S2 MB.
    """
    from ghg_tool.application.calc.scope2_mb import _FACTOR_ID_GO_ZERO, _FACTOR_ID_RESIDUAL

    strumento = req.strumento_mb  # already validated non-None
    factor_id = _FACTOR_ID_GO_ZERO if strumento == "GO" else _FACTOR_ID_RESIDUAL

    factor = require_factor(
        catalog, factor_id, gwp_set=req.gwp_set, vintage_year=req.anno
    )

    quantita = req.quantita
    unit_desc: str | None = None
    if req.unita.lower() not in ("kwh",):
        quantita, unit_desc = _apply_unit_conversion(req.quantita, req.unita, "kWh")

    fv = factor.value or Decimal("0")
    tco2e = _quantize_tco2e(fv * quantita * KG_TO_TONNE)

    warnings: list[str] = []
    if factor.vintage and str(factor.vintage) != str(req.anno):
        warnings.append(
            f"Vintage {factor.vintage} used (closest-prior to {req.anno} request)"
        )
    if strumento == "GO":
        warnings.append("GO instrument applied: tCO2e = 0 (market-based zero factor)")
    elif strumento == "PPA":
        warnings.append("PPA instrument mapped to Italian AIB residual mix per market rules")

    formula = (
        f"{quantita} kWh × {fv} kgCO2e/kWh × 1e-3 = {tco2e} tCO2e "
        f"(strumento_mb={strumento!r})"
    )

    return CalcPreviewResponse(
        tco2e=tco2e,
        co2_biogenic_tonne=None,
        co2_fossil_tonne=_quantize_tco2e(tco2e) if tco2e > 0 else None,
        factor_id=factor.factor_id,
        factor_value=fv,
        factor_unit=factor.unit,
        factor_source=factor.source,
        factor_version=factor.version,
        factor_vintage=str(factor.vintage or req.anno),
        gwp_set=req.gwp_set,
        gwp_value=Decimal("1"),
        methodology="market-based",
        formula_human=formula,
        unit_conversion_applied=unit_desc,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# S3 sub-handlers
# ---------------------------------------------------------------------------

def _preview_s3_cat1(
    req: CalcInputRequest,
    catalog: FactorCatalogPort,
) -> CalcPreviewResponse:
    """Scope 3 Cat 1: mass-based ecoinvent or spend-based EXIOBASE.

    Supports ADR-007 biogenic split for cardboard/pallet factors.

    Args:
        req: Validated CalcInputRequest.
        catalog: Factor catalog port.

    Returns:
        CalcPreviewResponse with optional biogenic memo.
    """
    from ghg_tool.application.calc.scope3_cat1_purchased_goods import (
        _BIOGENIC_FACTOR_IDS,
        _MATERIAL_FACTOR_MAP,
        _SPEND_FACTOR_MAP,
    )

    sub = (req.sottocategoria or "").strip().lower()
    factor_id = _MATERIAL_FACTOR_MAP.get(sub) or _SPEND_FACTOR_MAP.get(sub)
    if factor_id is None:
        raise MissingFactorError(
            f"No Cat 1 factor found for sottocategoria={req.sottocategoria!r}. "
            f"Known: {sorted({**_MATERIAL_FACTOR_MAP, **_SPEND_FACTOR_MAP})}"
        )

    factor = require_factor(
        catalog, factor_id, gwp_set=req.gwp_set, vintage_year=req.anno
    )
    quantita = req.quantita

    tco2e_kg = (factor.value or Decimal("0")) * quantita
    tco2e = _quantize_tco2e(tco2e_kg * KG_TO_TONNE)

    co2_biogenic: Decimal | None = None
    co2_fossil: Decimal | None = None
    if factor_id in _BIOGENIC_FACTOR_IDS:
        bio = catalog.get_biogenic_share(factor_id, gwp_set=req.gwp_set)
        if bio is not None:
            co2_biogenic = _quantize_tco2e(bio * quantita * KG_TO_TONNE)
            co2_fossil = tco2e  # fossil == total (biogenic is memo-only, not subtracted)

    methodology = "mass-based" if factor_id.startswith("ECOINV_") else "spend-based"

    warnings: list[str] = []
    if factor.vintage and str(factor.vintage) != str(req.anno):
        warnings.append(
            f"Vintage {factor.vintage} used (closest-prior to {req.anno} request)"
        )

    fv = factor.value or Decimal("0")
    formula = (
        f"{quantita} kg × {fv} kgCO2e/kg × 1e-3 = {tco2e} tCO2e "
        f"[{req.sottocategoria} via {factor_id}]"
    )
    if co2_biogenic is not None:
        formula += f"; biogenic memo: {co2_biogenic} tCO2 (ADR-007, not in tco2e)"

    return CalcPreviewResponse(
        tco2e=tco2e,
        co2_biogenic_tonne=co2_biogenic,
        co2_fossil_tonne=co2_fossil,
        factor_id=factor.factor_id,
        factor_value=fv,
        factor_unit=factor.unit,
        factor_source=factor.source,
        factor_version=factor.version,
        factor_vintage=str(factor.vintage or req.anno),
        gwp_set=req.gwp_set,
        gwp_value=None,
        methodology=methodology,
        formula_human=formula,
        unit_conversion_applied=None,
        warnings=warnings,
    )


def _preview_s3_cat3(
    req: CalcInputRequest,
    catalog: FactorCatalogPort,
) -> CalcPreviewResponse:
    """Scope 3 Cat 3: WTT + T&D — user supplies sub-category fuel/electricity key.

    sottocategoria maps to WTT/TND factor IDs from scope3_cat3_fuel_energy.

    Args:
        req: Validated CalcInputRequest.
        catalog: Factor catalog port.

    Returns:
        CalcPreviewResponse for the matched WTT or TND factor.
    """
    from ghg_tool.application.calc.scope3_cat3_fuel_energy import (
        _ELEC_WTT_ID,
        _FUEL_WTT_FACTOR_IDS,
        _TND_ELEC_IT_ID,
    )

    sub = (req.sottocategoria or "").strip().upper()

    # Map sottocategoria to factor_id
    if sub in _FUEL_WTT_FACTOR_IDS:
        factor_id = _FUEL_WTT_FACTOR_IDS[sub]
        methodology = "activity-based"
    elif sub in ("WTT_ELEC", "ELECTRICITY_WTT", "ELEC_WTT"):
        factor_id = _ELEC_WTT_ID
        methodology = "activity-based"
    elif sub in ("TND", "TND_ELEC", "T&D", "T_AND_D"):
        factor_id = _TND_ELEC_IT_ID
        methodology = "activity-based"
    else:
        raise MissingFactorError(
            f"No Cat 3 WTT/TND factor for sottocategoria={req.sottocategoria!r}. "
            f"Known fuel keys: {sorted(_FUEL_WTT_FACTOR_IDS)}, "
            f"electricity: 'WTT_ELEC', T&D: 'TND'"
        )

    factor = require_factor(
        catalog, factor_id, gwp_set=req.gwp_set, vintage_year=req.anno
    )
    quantita = req.quantita

    tco2e = _quantize_tco2e((factor.value or Decimal("0")) * quantita * KG_TO_TONNE)

    warnings: list[str] = []
    if factor.vintage and str(factor.vintage) != str(req.anno):
        warnings.append(
            f"Vintage {factor.vintage} used (closest-prior to {req.anno} request)"
        )

    fv = factor.value or Decimal("0")
    formula = (
        f"{quantita} {req.unita} × {fv} kgCO2e/{req.unita} × 1e-3 = {tco2e} tCO2e "
        f"[Cat3 WTT/TND {req.sottocategoria}]"
    )

    return CalcPreviewResponse(
        tco2e=tco2e,
        co2_biogenic_tonne=None,
        co2_fossil_tonne=None,
        factor_id=factor.factor_id,
        factor_value=fv,
        factor_unit=factor.unit,
        factor_source=factor.source,
        factor_version=factor.version,
        factor_vintage=str(factor.vintage or req.anno),
        gwp_set=req.gwp_set,
        gwp_value=None,
        methodology=methodology,
        formula_human=formula,
        unit_conversion_applied=None,
        warnings=warnings,
    )


def _preview_s3_cat4(
    req: CalcInputRequest,
    catalog: FactorCatalogPort,
) -> CalcPreviewResponse:
    """Scope 3 Cat 4 upstream transport: tkm × DEFRA mode factor.

    Args:
        req: Validated CalcInputRequest.
        catalog: Factor catalog port.

    Returns:
        CalcPreviewResponse for Cat 4 distance-based transport.
    """
    from ghg_tool.application.calc.scope3_cat4_upstream_transport import _resolve_mode

    sub = req.sottocategoria or ""
    factor_id = _resolve_mode(sub)
    if factor_id is None:
        raise MissingFactorError(
            f"No Cat 4 transport factor for sottocategoria={sub!r}. "
            "Accepted mode keywords: strada/hgv/camion, treno/rail, nave/sea/mare."
        )

    factor = require_factor(
        catalog, factor_id, gwp_set=req.gwp_set, vintage_year=req.anno
    )
    tkm = req.quantita
    tco2e = _quantize_tco2e((factor.value or Decimal("0")) * tkm * KG_TO_TONNE)

    warnings: list[str] = []
    if factor.vintage and str(factor.vintage) != str(req.anno):
        warnings.append(
            f"Vintage {factor.vintage} used (closest-prior to {req.anno} request)"
        )

    fv = factor.value or Decimal("0")
    formula = f"{tkm} tkm × {fv} kgCO2e/tkm × 1e-3 = {tco2e} tCO2e [{sub}]"

    return CalcPreviewResponse(
        tco2e=tco2e,
        co2_biogenic_tonne=None,
        co2_fossil_tonne=None,
        factor_id=factor.factor_id,
        factor_value=fv,
        factor_unit=factor.unit,
        factor_source=factor.source,
        factor_version=factor.version,
        factor_vintage=str(factor.vintage or req.anno),
        gwp_set=req.gwp_set,
        gwp_value=None,
        methodology="distance-based",
        formula_human=formula,
        unit_conversion_applied=None,
        warnings=warnings,
    )


def _preview_s3_cat5(
    req: CalcInputRequest,
    catalog: FactorCatalogPort,
) -> CalcPreviewResponse:
    """Scope 3 Cat 5 waste: mass × DEFRA waste factor (cut-off methodology).

    Args:
        req: Validated CalcInputRequest.
        catalog: Factor catalog port.

    Returns:
        CalcPreviewResponse for Cat 5 waste.
    """
    from ghg_tool.application.calc.scope3_cat5_waste import _resolve_waste_factor

    sub = req.sottocategoria or ""
    factor_id = _resolve_waste_factor(sub)
    if factor_id is None:
        raise MissingFactorError(
            f"No Cat 5 waste factor for sottocategoria={sub!r}. "
            "Include 'discarica/landfill' or 'ricicl/recycl' and optionally "
            "'pericolosi' (hazardous) or 'non pericolosi' (non-hazardous)."
        )

    factor = require_factor(
        catalog, factor_id, gwp_set=req.gwp_set, vintage_year=req.anno
    )
    tonnes = req.quantita
    tco2e = _quantize_tco2e((factor.value or Decimal("0")) * tonnes * KG_TO_TONNE)

    warnings: list[str] = []
    if factor.vintage and str(factor.vintage) != str(req.anno):
        warnings.append(
            f"Vintage {factor.vintage} used (closest-prior to {req.anno} request)"
        )

    fv = factor.value or Decimal("0")
    formula = f"{tonnes} t × {fv} kgCO2e/t × 1e-3 = {tco2e} tCO2e [{sub}]"

    return CalcPreviewResponse(
        tco2e=tco2e,
        co2_biogenic_tonne=None,
        co2_fossil_tonne=None,
        factor_id=factor.factor_id,
        factor_value=fv,
        factor_unit=factor.unit,
        factor_source=factor.source,
        factor_version=factor.version,
        factor_vintage=str(factor.vintage or req.anno),
        gwp_set=req.gwp_set,
        gwp_value=None,
        methodology="mass-based",
        formula_human=formula,
        unit_conversion_applied=None,
        warnings=warnings,
    )


def _preview_s3_cat6(
    req: CalcInputRequest,
    catalog: FactorCatalogPort,
) -> CalcPreviewResponse:
    """Scope 3 Cat 6 business travel: spend × DEFRA factor.

    Args:
        req: Validated CalcInputRequest.
        catalog: Factor catalog port.

    Returns:
        CalcPreviewResponse for Cat 6 spend-based travel.
    """
    from ghg_tool.application.calc.scope3_cat6_business_travel import _resolve_factor

    sub = req.sottocategoria or ""
    factor_id = _resolve_factor(sub)
    if factor_id is None:
        raise MissingFactorError(
            f"No Cat 6 travel factor for sottocategoria={sub!r}. "
            "Known: 'voli' (flights), 'auto noleggio' (hire car), 'hotel'."
        )

    factor = require_factor(
        catalog, factor_id, gwp_set=req.gwp_set, vintage_year=req.anno
    )
    spend = req.quantita
    tco2e = _quantize_tco2e((factor.value or Decimal("0")) * spend * KG_TO_TONNE)

    warnings: list[str] = []
    if factor.vintage and str(factor.vintage) != str(req.anno):
        warnings.append(
            f"Vintage {factor.vintage} used (closest-prior to {req.anno} request)"
        )

    fv = factor.value or Decimal("0")
    formula = (
        f"{spend} {req.unita} × {fv} kgCO2e/{req.unita} × 1e-3 = {tco2e} tCO2e [{sub}]"
    )

    return CalcPreviewResponse(
        tco2e=tco2e,
        co2_biogenic_tonne=None,
        co2_fossil_tonne=None,
        factor_id=factor.factor_id,
        factor_value=fv,
        factor_unit=factor.unit,
        factor_source=factor.source,
        factor_version=factor.version,
        factor_vintage=str(factor.vintage or req.anno),
        gwp_set=req.gwp_set,
        gwp_value=None,
        methodology="spend-based",
        formula_human=formula,
        unit_conversion_applied=None,
        warnings=warnings,
    )


def _preview_s3_cat7(
    req: CalcInputRequest,
    catalog: FactorCatalogPort,
) -> CalcPreviewResponse:
    """Scope 3 Cat 7 commuting: km × DEFRA average-car factor.

    Args:
        req: Validated CalcInputRequest.
        catalog: Factor catalog port.

    Returns:
        CalcPreviewResponse for Cat 7 distance-based commuting.
    """
    from ghg_tool.application.calc.scope3_cat7_commuting import _FACTOR_ID as CAT7_FACTOR_ID

    factor = require_factor(
        catalog, CAT7_FACTOR_ID, gwp_set=req.gwp_set, vintage_year=req.anno
    )
    km = req.quantita
    tco2e = _quantize_tco2e((factor.value or Decimal("0")) * km * KG_TO_TONNE)

    warnings: list[str] = []
    if factor.vintage and str(factor.vintage) != str(req.anno):
        warnings.append(
            f"Vintage {factor.vintage} used (closest-prior to {req.anno} request)"
        )

    sub = req.sottocategoria or ""
    if sub.strip().lower() != "commuting_auto":
        warnings.append(
            f"Cat 7 factor is average-car (DEFRA); "
            f"sottocategoria={sub!r} != 'commuting_auto' — verify mode applicability."
        )

    fv = factor.value or Decimal("0")
    formula = f"{km} km × {fv} kgCO2e/km × 1e-3 = {tco2e} tCO2e [Cat7 commuting]"

    return CalcPreviewResponse(
        tco2e=tco2e,
        co2_biogenic_tonne=None,
        co2_fossil_tonne=None,
        factor_id=factor.factor_id,
        factor_value=fv,
        factor_unit=factor.unit,
        factor_source=factor.source,
        factor_version=factor.version,
        factor_vintage=str(factor.vintage or req.anno),
        gwp_set=req.gwp_set,
        gwp_value=None,
        methodology="distance-based",
        formula_human=formula,
        unit_conversion_applied=None,
        warnings=warnings,
    )


def _preview_s3_cat9(
    req: CalcInputRequest,
    catalog: FactorCatalogPort,
) -> CalcPreviewResponse:
    """Scope 3 Cat 9 downstream transport: tkm × DEFRA freight factor.

    Args:
        req: Validated CalcInputRequest.
        catalog: Factor catalog port.

    Returns:
        CalcPreviewResponse for Cat 9 downstream transport.
    """
    from ghg_tool.application.calc.scope3_cat9_downstream_transport import _resolve_mode

    sub = req.sottocategoria or ""
    factor_id = _resolve_mode(sub)
    if factor_id is None:
        raise MissingFactorError(
            f"No Cat 9 transport factor for sottocategoria={sub!r}. "
            "Accepted mode keywords: strada/hgv, nave/sea/mare."
        )

    factor = require_factor(
        catalog, factor_id, gwp_set=req.gwp_set, vintage_year=req.anno
    )
    tkm = req.quantita
    tco2e = _quantize_tco2e((factor.value or Decimal("0")) * tkm * KG_TO_TONNE)

    warnings: list[str] = []
    if factor.vintage and str(factor.vintage) != str(req.anno):
        warnings.append(
            f"Vintage {factor.vintage} used (closest-prior to {req.anno} request)"
        )

    fv = factor.value or Decimal("0")
    formula = f"{tkm} tkm × {fv} kgCO2e/tkm × 1e-3 = {tco2e} tCO2e [{sub}]"

    return CalcPreviewResponse(
        tco2e=tco2e,
        co2_biogenic_tonne=None,
        co2_fossil_tonne=None,
        factor_id=factor.factor_id,
        factor_value=fv,
        factor_unit=factor.unit,
        factor_source=factor.source,
        factor_version=factor.version,
        factor_vintage=str(factor.vintage or req.anno),
        gwp_set=req.gwp_set,
        gwp_value=None,
        methodology="distance-based",
        formula_human=formula,
        unit_conversion_applied=None,
        warnings=warnings,
    )


def _preview_s3_cat12(
    req: CalcInputRequest,
    catalog: FactorCatalogPort,
) -> CalcPreviewResponse:
    """Scope 3 Cat 12 EOL: 30/70 landfill/recycle split × ecoinvent factors.

    Returns tco2e as the sum of both fractions (combined headline).

    Args:
        req: Validated CalcInputRequest.
        catalog: Factor catalog port.

    Returns:
        CalcPreviewResponse with combined landfill+recycle tco2e.
    """
    from ghg_tool.application.calc.scope3_cat12_eol import (
        _LANDFILL_FACTOR_ID,
        _LANDFILL_FRACTION,
        _RECYCLE_FACTOR_ID,
        _RECYCLE_FRACTION,
    )

    landfill_factor = require_factor(
        catalog, _LANDFILL_FACTOR_ID, gwp_set=req.gwp_set, vintage_year=req.anno
    )
    recycle_factor = require_factor(
        catalog, _RECYCLE_FACTOR_ID, gwp_set=req.gwp_set, vintage_year=req.anno
    )

    mass_t = req.quantita
    landfill_mass = mass_t * _LANDFILL_FRACTION
    recycle_mass = mass_t * _RECYCLE_FRACTION

    landfill_tco2e = (landfill_factor.value or Decimal("0")) * landfill_mass * KG_TO_TONNE
    recycle_tco2e = (recycle_factor.value or Decimal("0")) * recycle_mass * KG_TO_TONNE
    tco2e = _quantize_tco2e(landfill_tco2e + recycle_tco2e)

    warnings: list[str] = []
    if landfill_factor.vintage and str(landfill_factor.vintage) != str(req.anno):
        warnings.append(
            f"Vintage {landfill_factor.vintage} used "
            f"(closest-prior to {req.anno} request)"
        )

    lfv = landfill_factor.value or Decimal("0")
    rfv = recycle_factor.value or Decimal("0")
    lf_q = _quantize_tco2e(landfill_tco2e)
    rf_q = _quantize_tco2e(recycle_tco2e)
    formula = (
        f"{mass_t} t × (30% landfill: {landfill_mass} t × {lfv} kgCO2e/kg × 1e-3 = "
        f"{lf_q} tCO2e) + "
        f"(70% recycle: {recycle_mass} t × {rfv} kgCO2e/kg × 1e-3 = "
        f"{rf_q} tCO2e) = {tco2e} tCO2e"
    )

    return CalcPreviewResponse(
        tco2e=tco2e,
        co2_biogenic_tonne=None,
        co2_fossil_tonne=None,
        factor_id=landfill_factor.factor_id,
        factor_value=lfv,
        factor_unit=landfill_factor.unit,
        factor_source=landfill_factor.source,
        factor_version=landfill_factor.version,
        factor_vintage=str(landfill_factor.vintage or req.anno),
        gwp_set=req.gwp_set,
        gwp_value=None,
        methodology="mass-based",
        formula_human=formula,
        unit_conversion_applied=None,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_DISPATCH: dict[tuple[int, str], Any] = {
    (1, "combustion"): _preview_s1_combustion,
    (1, "process"): _preview_s1_process,
    (2, "lb"): _preview_s2_lb,
    (2, "mb"): _preview_s2_mb,
    (3, "cat1_purchased_goods"): _preview_s3_cat1,
    (3, "cat3_fuel_energy"): _preview_s3_cat3,
    (3, "cat4_upstream_transport"): _preview_s3_cat4,
    (3, "cat5_waste"): _preview_s3_cat5,
    (3, "cat6_business_travel"): _preview_s3_cat6,
    (3, "cat7_commuting"): _preview_s3_cat7,
    (3, "cat9_downstream_transport"): _preview_s3_cat9,
    (3, "cat12_eol"): _preview_s3_cat12,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def compute_preview(
    request: CalcInputRequest,
    *,
    factor_catalog: FactorCatalogPort,
    session: Any = None,
    tenant_id: str | None = None,
) -> CalcPreviewResponse:
    """Compute a tCO2e preview for the given request without writing to the DB.

    Dispatches to the appropriate sub-handler based on (scope, sub_scope).
    All sub-handlers reuse existing application/calc/* factor IDs and logic.

    M6 additions:
        - Task B: when ``session`` is provided and sub_scope == 'process',
          looks up ``site_type`` from ref.sites and rejects non-
          STABILIMENTO_PRODUTTIVO sites with HTTP 422.
        - Task C: when ``session`` is provided and sub_scope == 'lb',
          reads ``country`` from ref.sites and passes it to _preview_s2_lb
          instead of the hardcoded 'IT' default.

    Args:
        request: Validated CalcInputRequest.
        factor_catalog: Factor catalog port (SQL adapter or test double).
        session: Optional async SQLAlchemy session.  When provided, site
            metadata is fetched for Tasks B and C.  When absent (e.g. in
            tests that do not inject a session), site validation is skipped
            and LB defaults to 'IT'.
        tenant_id: UUID string of the requesting tenant.  Required when
            ``session`` is provided.

    Returns:
        CalcPreviewResponse with full audit trace.

    Raises:
        HTTPException 422: For Task B site_type violations.
        MissingFactorError: Surfaces as HTTP 422 at router level.
        UnitConversionError: Surfaces as HTTP 422 at router level.
        ValueError: Validation failures surfaced as HTTP 422.
    """
    log = logger.bind(
        scope=request.scope,
        sub_scope=request.sub_scope,
        anno=request.anno,
        gwp_set=request.gwp_set,
    )
    log.info("auto_calc_preview_start")

    handler = _DISPATCH.get((request.scope, request.sub_scope))
    if handler is None:
        raise ValueError(
            f"No auto-calc handler for "
            f"scope={request.scope} sub_scope={request.sub_scope!r}"
        )

    # -----------------------------------------------------------------------
    # M6 Task B + Task C: site metadata lookup (requires session + codice_sito)
    # -----------------------------------------------------------------------
    site_meta: _SiteMeta | None = None
    if session is not None and tenant_id and request.codice_sito:
        site_meta = await _fetch_site_meta(
            session,
            codice_sito=request.codice_sito,
            tenant_id=tenant_id,
        )

    # Task B: Processo_Decarb is only allowed for STABILIMENTO_PRODUTTIVO
    if request.sub_scope == "process" and site_meta is not None:
        _assert_process_site_type(
            codice_sito=request.codice_sito or "",
            site_type=site_meta.site_type,
        )

    # Task C: use country from ref.sites for S2 LB
    if request.sub_scope == "lb" and site_meta is not None:
        country = site_meta.country
        preview: CalcPreviewResponse = _preview_s2_lb(
            request, factor_catalog, country=country
        )
    else:
        preview = handler(request, factor_catalog)

    log.info("auto_calc_preview_complete", tco2e=str(preview.tco2e))
    return preview


async def compute_and_insert(
    request: CalcInputRequest,
    *,
    factor_catalog: FactorCatalogPort,
    session: Any,
    user: Any,
) -> CalcInsertResponse:
    """Compute tCO2e and append a row to calc.emissions_consolidated.

    Steps:
        1. compute_preview() — all factor lookups and arithmetic (with site
           metadata lookup for Tasks B and C).
        2. INSERT into raw.direct_entry (Task D, FR-22).
        3. INSERT into calc.emissions_consolidated with raw_row_id pointing
           to the raw.direct_entry row (no more nil UUID sentinel).
        4. INSERT audit_log row (action='emission_auto_calc').
        5. All three inserts in the same session transaction.
        6. Return CalcInsertResponse with emission_id + correlation_id.

    Args:
        request: Validated CalcInputRequest.
        factor_catalog: Factor catalog port.
        session: Async SQLAlchemy session (with RLS GUCs already set by get_db).
        user: CurrentUser dependency (provides sub, tenant_id, role).

    Returns:
        CalcInsertResponse with DB identifiers.

    Raises:
        HTTPException 422: For Task B site_type violations or missing factors.
        MissingFactorError: Surfaces as HTTP 422.
        UnitConversionError: Surfaces as HTTP 422.
    """
    import json as _json  # noqa: PLC0415

    from sqlalchemy import text  # noqa: PLC0415

    log = logger.bind(
        scope=request.scope,
        sub_scope=request.sub_scope,
        anno=request.anno,
        gwp_set=request.gwp_set,
        user=user.sub,
    )
    log.info("auto_calc_insert_start")

    tenant_id: str = user.tenant_id

    # Step 1: compute preview (passes session for Task B + Task C)
    preview = await compute_preview(
        request,
        factor_catalog=factor_catalog,
        session=session,
        tenant_id=tenant_id,
    )

    # Step 2: generate IDs
    emission_id = uuid.uuid4()
    # Task D: raw.direct_entry gets its own UUID
    raw_entry_id = uuid.uuid4()
    correlation_id = uuid.UUID(get_correlation_id())
    now = datetime.now(UTC)

    # Resolve emissions_consolidated.factor_id FK -> ref.factor_catalog.id
    # by looking up the row whose business code matches the factor selected
    # by compute_preview. Falls back to nil UUID only if no row is found
    # (the FK constraint will then fail and the transaction rolls back —
    # surfacing a missing factor as a database error rather than a silent
    # nil-UUID corruption).
    nil_uuid = str(uuid.UUID(int=0))
    factor_uuid_row = await session.execute(
        text(
            "SELECT id FROM ref.factor_catalog "
            "WHERE tenant_id = CAST(:tid AS uuid) "
            "  AND factor_id = :code "
            "  AND gwp_set = :gwp "
            "ORDER BY valid_from DESC LIMIT 1"
        ),
        {
            "tid": str(tenant_id),
            "code": preview.factor_id,
            "gwp": request.gwp_set,
        },
    )
    factor_uuid_scalar = factor_uuid_row.scalar_one_or_none()
    factor_uuid_fk = (
        str(factor_uuid_scalar) if factor_uuid_scalar is not None else nil_uuid
    )

    sub_scope_map: dict[str, str] = {
        "combustion": "combustion",
        "process": "process",
        "lb": "LB",
        "mb": "MB",
        "cat1_purchased_goods": "Cat1",
        "cat3_fuel_energy": "Cat3_WTT_FUEL",
        "cat4_upstream_transport": "Cat4",
        "cat5_waste": "Cat5",
        "cat6_business_travel": "Cat6",
        "cat7_commuting": "Cat7",
        "cat9_downstream_transport": "Cat9",
        "cat12_eol": "Cat12",
    }
    db_sub_scope = sub_scope_map.get(request.sub_scope, request.sub_scope)

    # -----------------------------------------------------------------------
    # Task D — Step 2a: INSERT into raw.direct_entry
    # Stores the original user request payload + resolved factor metadata
    # for FR-22 universal traceability.
    # -----------------------------------------------------------------------
    request_payload = _json.dumps(request.model_dump(mode="json"), sort_keys=True)

    insert_raw_sql = text(
        """
        INSERT INTO raw.direct_entry (
            id, tenant_id, correlation_id, inserted_by, inserted_at,
            request_payload, factor_id, factor_vintage, tco2e
        ) VALUES (
            CAST(:id AS uuid),
            CAST(:tenant_id AS uuid),
            CAST(:correlation_id AS uuid),
            :inserted_by,
            :inserted_at,
            CAST(:request_payload AS jsonb),
            :factor_id,
            :factor_vintage,
            :tco2e
        )
        """
    )

    # Resolve factor_vintage: use integer form if possible, else current anno
    try:
        factor_vintage_int = int(preview.factor_vintage)
    except (ValueError, TypeError):
        factor_vintage_int = request.anno

    await session.execute(
        insert_raw_sql,
        {
            "id": str(raw_entry_id),
            "tenant_id": str(tenant_id),
            "correlation_id": str(correlation_id),
            "inserted_by": user.sub,
            "inserted_at": now,
            "request_payload": request_payload,
            "factor_id": preview.factor_id,
            "factor_vintage": factor_vintage_int,
            "tco2e": float(preview.tco2e),
        },
    )
    log.info("raw_direct_entry_inserted", raw_entry_id=str(raw_entry_id))

    # -----------------------------------------------------------------------
    # Task D — Step 2b: INSERT into calc.emissions_consolidated
    # raw_row_id now references the raw.direct_entry row (not nil UUID).
    # -----------------------------------------------------------------------
    insert_emission_sql = text(
        """
        INSERT INTO calc.emissions_consolidated (
            id, tenant_id, correlation_id, raw_row_id, raw_scope, scope, sub_scope,
            codice_sito, anno, tco2e, co2_tonne, ch4_tco2e, n2o_tco2e,
            co2_biogenic_tonne, co2_fossil_tonne,
            factor_id, factor_version, factor_source, gwp_set,
            methodology, regulatory_stream, calc_timestamp, created_by,
            valid_from, valid_to, superseded_by, reason_code, disclosure_notes
        ) VALUES (
            :id, :tenant_id, :correlation_id, :raw_row_id, :raw_scope, :scope, :sub_scope,
            :codice_sito, :anno, :tco2e, :co2_tonne, :ch4_tco2e, :n2o_tco2e,
            :co2_biogenic_tonne, :co2_fossil_tonne,
            :factor_id, :factor_version, :factor_source, :gwp_set,
            :methodology, :regulatory_stream, :calc_timestamp, :created_by,
            :valid_from, :valid_to, :superseded_by, :reason_code, :disclosure_notes
        )
        """
    )

    await session.execute(
        insert_emission_sql,
        {
            "id": str(emission_id),
            "tenant_id": str(tenant_id),
            "correlation_id": str(correlation_id),
            # Task D: raw_row_id now references raw.direct_entry (FR-22)
            "raw_row_id": str(raw_entry_id),
            "raw_scope": request.scope,
            "scope": request.scope,
            "sub_scope": db_sub_scope,
            "codice_sito": request.codice_sito,
            "anno": request.anno,
            "tco2e": preview.tco2e,
            "co2_tonne": None,
            "ch4_tco2e": None,
            "n2o_tco2e": None,
            "co2_biogenic_tonne": preview.co2_biogenic_tonne,
            "co2_fossil_tonne": preview.co2_fossil_tonne,
            "factor_id": factor_uuid_fk,
            "factor_version": preview.factor_version,
            "factor_source": preview.factor_source,
            "gwp_set": request.gwp_set,
            "methodology": preview.methodology,
            "regulatory_stream": "CSRD_ESRS_E1",
            "calc_timestamp": now,
            "created_by": f"api:{user.sub}",
            "valid_from": now,
            "valid_to": None,
            "superseded_by": None,
            "reason_code": None,
            "disclosure_notes": (
                f"auto_calc via API: {preview.formula_human} "
                f"(fonte_dato={request.fonte_dato}, "
                f"qualita_dato={request.qualita_dato})"
            ),
        },
    )

    # Step 3 (was step 3 before): audit log (append-only)
    insert_audit_sql = text(
        """
        INSERT INTO calc.audit_log (
            id, tenant_id, correlation_id, user_id, user_role,
            action, resource, resource_id, request_method, request_path,
            status_code, after_state
        ) VALUES (
            :id, :tenant_id, :correlation_id, :user_id, :user_role,
            :action, :resource, :resource_id, :request_method, :request_path,
            :status_code, CAST(:after_state AS jsonb)
        )
        """
    )

    await session.execute(
        insert_audit_sql,
        {
            "id": str(uuid.uuid4()),
            "tenant_id": str(tenant_id),
            "correlation_id": str(correlation_id),
            "user_id": user.sub,
            "user_role": user.role,
            "action": "emission_auto_calc",
            "resource": "emissions",
            "resource_id": str(emission_id),
            "request_method": "POST",
            "request_path": "/api/v1/calc/insert",
            "status_code": 201,
            # PII-free: UUID only. JSON-encoded for asyncpg JSONB binding.
            "after_state": _json.dumps(
                {
                    "emission_id": str(emission_id),
                    "raw_entry_id": str(raw_entry_id),
                },
                sort_keys=True,
            ),
        },
    )

    log.info(
        "auto_calc_insert_complete",
        emission_id=str(emission_id),
        raw_entry_id=str(raw_entry_id),
        tco2e=str(preview.tco2e),
        correlation_id=str(correlation_id),
        idempotency_replayed=False,
    )

    return CalcInsertResponse(
        tco2e=preview.tco2e,
        co2_biogenic_tonne=preview.co2_biogenic_tonne,
        co2_fossil_tonne=preview.co2_fossil_tonne,
        factor_id=preview.factor_id,
        factor_value=preview.factor_value,
        factor_unit=preview.factor_unit,
        factor_source=preview.factor_source,
        factor_version=preview.factor_version,
        factor_vintage=preview.factor_vintage,
        gwp_set=preview.gwp_set,
        gwp_value=preview.gwp_value,
        methodology=preview.methodology,
        formula_human=preview.formula_human,
        unit_conversion_applied=preview.unit_conversion_applied,
        warnings=preview.warnings,
        # Insert-specific fields
        emission_id=emission_id,
        correlation_id=correlation_id,
        created_at=now,
    )

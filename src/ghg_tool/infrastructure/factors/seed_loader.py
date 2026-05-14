"""Factor catalog seed loader — Phase 5 helpers for TBC value pinning.

Responsibilities:
  - Verify which factor_ids still have TBC (is_tbc=True) values.
  - Provide stub functions for pinning authoritative numeric values from
    retrieved source PDFs (OI-5 closure at Phase 5).
  - Hash-pin PDF evidence for MinIO storage (ADR-008 path).

All pin functions are STUBS with TODO + URL references per
methodology_validation.md §13.  They raise NotImplementedError until
wave 2/Phase 5 completes the retrieval.

Import direction: infrastructure → domain (allowed).
"""

from __future__ import annotations

from decimal import Decimal

# ---------------------------------------------------------------------------
# TBC factor registry — update this dict as values are confirmed at Phase 5
# ---------------------------------------------------------------------------
_TBC_FACTOR_URLS: dict[str, str] = {
    "LB_IT_GRID_ISPRA_2024": (
        "https://emissioni.sina.isprambiente.it/wp-content/uploads/2025/05/"
        "Le-emissioni-di-CO2-nel-settore-elettrico_r413-2025_def.pdf"
    ),
    "MB_IT_RESIDUAL_AIB_2024": (
        "https://www.aib-net.org/facts/european-residual-mix/2024"
    ),
    "WTT_GAS_NAT_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "WTT_GASOLIO_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "WTT_BENZINA_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "WTT_ELEC_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "TND_ELEC_IT_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "FREIGHT_HGV_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "FREIGHT_RAIL_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "FREIGHT_SEA_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "TRAVEL_SPEND_FLIGHTS_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "TRAVEL_SPEND_HIRECAR_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "TRAVEL_SPEND_HOTEL_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMMUTE_CAR_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "WASTE_LANDFILL_PERIC_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "WASTE_LANDFILL_NONPERIC_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "WASTE_RECYCLE_PERIC_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "WASTE_RECYCLE_NONPERIC_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_GAS_NAT_CO2_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_GAS_NAT_CH4_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_GAS_NAT_N2O_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_GASOLIO_CO2_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_GASOLIO_CH4_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_GASOLIO_N2O_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_BENZINA_CO2_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_BENZINA_CH4_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "COMB_BENZINA_N2O_DEFRA_2025": (
        "https://www.gov.uk/government/collections/"
        "government-conversion-factors-for-company-reporting"
    ),
    "ECOINV_CARDBOARD_V3_10": "https://ecoinvent.org/ecoinvent-v3-10/",
    "ECOINV_PALLET_V3_10": "https://ecoinvent.org/ecoinvent-v3-10/",
}

# Deterministic values already seeded (no TBC)
_DETERMINISTIC_FACTORS: dict[str, Decimal] = {
    "STOICH_CACO3_IPCC_2006": Decimal("0.4397"),
    "MB_GO_ZERO": Decimal("0.0"),
}


def list_tbc_factor_ids() -> list[str]:
    """Return all factor IDs that are still pending numeric pinning.

    Returns:
        Sorted list of factor_id strings with TBC status.
    """
    return sorted(_TBC_FACTOR_URLS.keys())


def get_tbc_source_url(factor_id: str) -> str | None:
    """Return the authoritative source URL for a TBC factor.

    Args:
        factor_id: Factor identifier to look up.

    Returns:
        URL string, or None if factor_id is not in the TBC registry.
    """
    return _TBC_FACTOR_URLS.get(factor_id)


def get_deterministic_value(factor_id: str) -> Decimal | None:
    """Return the deterministic (non-TBC) value for a factor.

    Args:
        factor_id: Factor identifier.

    Returns:
        Decimal value, or None if not a deterministic factor.
    """
    return _DETERMINISTIC_FACTORS.get(factor_id)


def pin_defra_2025_value(factor_id: str, value: Decimal) -> None:
    """Stub: PIN a DEFRA 2025 factor value after manual PDF retrieval.

    To be implemented at Phase 5 when the data-engineer manually downloads
    the DEFRA 2025 conversion factors spreadsheet and reads the numeric
    values from the relevant tab.

    TODO: Implement by reading DEFRA 2025 spreadsheet from object store
    (ADR-008 MinIO path: minio://gh-tool-evidence/DEFRA_2025.xlsx).

    Args:
        factor_id: DEFRA factor identifier (e.g. 'WTT_GAS_NAT_DEFRA_2025').
        value: Confirmed numeric value from the official DEFRA publication.

    Raises:
        NotImplementedError: Always (stub for Phase 5 implementation).
    """
    raise NotImplementedError(
        f"pin_defra_2025_value not yet implemented. "
        f"Retrieve from: {get_tbc_source_url(factor_id)}"
    )


def pin_ispra_lb_factor(value: Decimal) -> None:
    """Stub: PIN ISPRA Italian grid LB emission factor for FY2024.

    TODO: Retrieve from ISPRA Rapporto 413/2025 (URL below) and pin the
    consumption-side factor for Italy FY2024 (or FY2023 with offset if
    2024 vintage not yet published).

    URL: https://emissioni.sina.isprambiente.it/wp-content/uploads/2025/05/
         Le-emissioni-di-CO2-nel-settore-elettrico_r413-2025_def.pdf

    Args:
        value: Confirmed numeric value (kg CO2/kWh).

    Raises:
        NotImplementedError: Always (stub for Phase 5 implementation).
    """
    raise NotImplementedError(
        "pin_ispra_lb_factor not yet implemented. "
        "Retrieve from ISPRA Rapporto 413/2025 (see methodology_validation §13 ref 19)."
    )


def pin_aib_residual_mix_2024(value: Decimal) -> None:
    """Stub: PIN AIB Italian residual mix 2024 numeric value.

    TODO: Manually retrieve from AIB European Residual Mix 2024 PDF
    (published 2025-05-30).  HTTP 403 was returned during Phase 2 validation
    (see methodology_validation §4.5).  MG-15 gate — blocks MB calculation
    for non-GO kWh.

    URL: https://www.aib-net.org/facts/european-residual-mix/2024

    Args:
        value: Confirmed numeric value (kg CO2e/kWh) for Italian residual mix.

    Raises:
        NotImplementedError: Always (stub for Phase 5 implementation).
    """
    raise NotImplementedError(
        "pin_aib_residual_mix_2024 not yet implemented. "
        "Retrieve from AIB ERM 2024 PDF (MG-15 gate, see methodology_validation §4.5)."
    )


def hash_pin_pdf_evidence(factor_id: str, pdf_path: str) -> str:
    """Compute SHA-256 hash of a factor source PDF for MinIO provenance.

    TODO: Extend to upload PDF to MinIO at the ADR-008 path and store the
    resulting URI in factor_catalog.pdf_source_uri.

    Args:
        factor_id: Factor identifier (for naming the MinIO object).
        pdf_path: Local path to the retrieved PDF.

    Returns:
        SHA-256 hex digest of the PDF file.
    """
    import hashlib
    from pathlib import Path

    p = Path(pdf_path)
    if not p.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    digest = h.hexdigest()
    # TODO (ADR-008): upload to minio://gh-tool-evidence/{factor_id}_{digest[:8]}.pdf
    return digest

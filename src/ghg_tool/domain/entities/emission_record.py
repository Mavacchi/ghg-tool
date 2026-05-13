"""Domain entity: EmissionRecord — frozen, slots-based dataclass.

Output type produced by every calc module under
``ghg_tool.application.calc``.  Mirrors the calc.emissions_consolidated
schema documented in architecture.md §8.2 / §9, with the ADR-007
biogenic CO2 split columns and FR-34 dual-track ``regulatory_stream``
tag.

The class is immutable (``frozen=True``, ``slots=True``).  Any attempted
mutation raises ``dataclasses.FrozenInstanceError`` — first line of
defence behind the DB trigger ``trg_emissions_deny_mutation``.

No framework imports — pure Python with stdlib + domain.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from ghg_tool.domain.exceptions.calc_errors import (
    InvalidSubScopeError,
    NegativeEmissionError,
)

# ---------------------------------------------------------------------------
# Sub-scope vocabulary per scope (architecture.md §8 / §9)
# ---------------------------------------------------------------------------

_ALLOWED_SUB_SCOPES: dict[int, frozenset[str]] = {
    1: frozenset({"combustion", "process", "fugitive"}),
    2: frozenset({"LB", "MB"}),
    3: frozenset({
        "Cat1", "Cat2",
        "Cat3_WTT_FUEL", "Cat3_WTT_ELEC", "Cat3_TND",
        "Cat4", "Cat5", "Cat6", "Cat7",
        "Cat8_ZERO", "Cat9", "Cat10_ZERO", "Cat11_ZERO",
        "Cat12", "Cat13_ZERO", "Cat14_ZERO", "Cat15_ZERO",
    }),
}

_ALLOWED_METHODOLOGIES: frozenset[str] = frozenset({
    "activity-based",
    "mass-based",
    "spend-based",
    "distance-based",
    "stoichiometric",
    "declared-zero",
    "location-based",
    "market-based",
})

_ALLOWED_REGULATORY_STREAMS: frozenset[str] = frozenset({
    "CSRD_ESRS_E1",
    "EU_ETS_PHASE_IV",
})

_ALLOWED_GWP_SETS: frozenset[str] = frozenset({"AR6", "AR5"})

RegulatoryStream = Literal["CSRD_ESRS_E1", "EU_ETS_PHASE_IV"]
GWPSetCode = Literal["AR6", "AR5"]


@dataclass(frozen=True, slots=True)
class EmissionRecord:
    """Immutable emission row produced by a calc module.

    Maps 1:1 onto a row in ``calc.emissions_consolidated``.  Every field
    that exists in the DB table is reflected here.  Domain stays
    framework-free: this class has no SQLAlchemy / Pydantic dependency.

    Attributes:
        id: UUID of the record (uuid4 default; persistence may keep or replace).
        correlation_id: Run identifier shared by all rows in a calc run.
        raw_row_id: FK back to the raw_*_ingestions row.  ``None`` for
            synthesised zero-lines (FR-18 Cat 11, FR-35 fugitive, FR-36).
        scope: 1, 2, or 3.
        sub_scope: One of ``_ALLOWED_SUB_SCOPES[scope]``.
        codice_sito: 7-site code or ``None`` for corporate-level rows
            (most Scope 3 rows; FR-36 zero-lines).
        anno: Reporting year.
        tco2e: Total tonnes CO2-equivalent.  GWP-weighted sum of non-CO2
            gases plus CO2 fossil (biogenic is memo-only per ADR-007).
        co2_tonne: Direct CO2 mass (combustion + process).  Optional.
        co2_biogenic_tonne: Biogenic CO2 memo line (ADR-007).
        co2_fossil_tonne: Fossil CO2 component (ADR-007).
        ch4_tco2e: CH4 contribution in CO2e (GWP-weighted).
        n2o_tco2e: N2O contribution in CO2e (GWP-weighted).
        factor_id: Catalog key (e.g. ``STOICH_CACO3_IPCC_2006``).
        factor_id_uuid: FK to ref.factor_catalog.id (denormalised UUID).
        factor_version: Version tag of the factor used.
        factor_source: Provider (DEFRA / ISPRA / AIB / ecoinvent v3.10 / IPCC).
        gwp_set: AR6 (CSRD default) or AR5 (EU ETS dual-track).
        methodology: One of ``_ALLOWED_METHODOLOGIES``.
        regulatory_stream: CSRD_ESRS_E1 or EU_ETS_PHASE_IV.
        calc_timestamp: UTC datetime at calc run.
        created_by: Username or service account identifier.
        valid_from: When this row becomes active (UTC).
        valid_to: When this row was superseded (UTC) or None if active.
        superseded_by: UUID of the replacement row in the correction chain.
        reason_code: Reason for a correction (FR-21 / fn_emit_correction).
        disclosure_notes: Free-text annotation; populated for FR-18, FR-35,
            FR-36 zero-lines and for MG-09 LOI uncertainty disclosure.
        uncertainty_band_lower: Lower 95% CI bound from bootstrap (Cat 6).
        uncertainty_band_upper: Upper 95% CI bound from bootstrap (Cat 6).
    """

    correlation_id: uuid.UUID
    raw_row_id: uuid.UUID | None
    scope: int
    sub_scope: str
    codice_sito: str | None
    anno: int
    tco2e: Decimal
    factor_id: str
    factor_version: str
    factor_source: str
    gwp_set: str
    methodology: str
    regulatory_stream: str
    calc_timestamp: datetime
    created_by: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    co2_tonne: Decimal | None = None
    co2_biogenic_tonne: Decimal | None = None
    co2_fossil_tonne: Decimal | None = None
    ch4_tco2e: Decimal | None = None
    n2o_tco2e: Decimal | None = None
    factor_id_uuid: uuid.UUID | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    superseded_by: uuid.UUID | None = None
    reason_code: str | None = None
    disclosure_notes: str | None = None
    uncertainty_band_lower: Decimal | None = None
    uncertainty_band_upper: Decimal | None = None

    def __post_init__(self) -> None:
        """Validate invariants per requirements + architecture.

        Raises:
            NegativeEmissionError: If tco2e < 0.
            InvalidSubScopeError: If sub_scope is not allowed for scope.
            ValueError: For other domain invariants (scope range, methodology,
                regulatory_stream, gwp_set, calc_timestamp naive).
        """
        if self.scope not in (1, 2, 3):
            raise ValueError(f"scope must be 1, 2, or 3 — got {self.scope!r}")
        if self.tco2e < Decimal("0"):
            raise NegativeEmissionError(
                f"tco2e must be >= 0; got {self.tco2e} "
                f"(scope={self.scope}, sub_scope={self.sub_scope!r})"
            )
        allowed = _ALLOWED_SUB_SCOPES[self.scope]
        if self.sub_scope not in allowed:
            raise InvalidSubScopeError(
                f"sub_scope={self.sub_scope!r} not allowed for scope={self.scope}. "
                f"Allowed: {sorted(allowed)}"
            )
        if self.methodology not in _ALLOWED_METHODOLOGIES:
            raise ValueError(
                f"methodology={self.methodology!r} not in {sorted(_ALLOWED_METHODOLOGIES)}"
            )
        if self.regulatory_stream not in _ALLOWED_REGULATORY_STREAMS:
            raise ValueError(
                f"regulatory_stream={self.regulatory_stream!r} "
                f"not in {sorted(_ALLOWED_REGULATORY_STREAMS)}"
            )
        if self.gwp_set not in _ALLOWED_GWP_SETS:
            raise ValueError(
                f"gwp_set={self.gwp_set!r} not in {sorted(_ALLOWED_GWP_SETS)}"
            )
        if self.calc_timestamp.tzinfo is None:
            raise ValueError(
                "calc_timestamp must be timezone-aware (UTC); naive datetime rejected"
            )
        # ADR-007: biogenic and fossil sum (when both present) must be >= 0
        if self.co2_biogenic_tonne is not None and self.co2_biogenic_tonne < Decimal("0"):
            raise ValueError(f"co2_biogenic_tonne must be >= 0 — got {self.co2_biogenic_tonne}")
        if self.co2_fossil_tonne is not None and self.co2_fossil_tonne < Decimal("0"):
            raise ValueError(f"co2_fossil_tonne must be >= 0 — got {self.co2_fossil_tonne}")

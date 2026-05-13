"""Pydantic v2 schemas for /emissions endpoints.

Mirrors ``calc.emissions_consolidated`` schema (architecture.md §4.3) and
the ``EmissionRecord`` domain entity, including ADR-007 biogenic columns
and FR-34 ``regulatory_stream`` tag.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Allowed value sets (must match DB CHECK constraints)
# ---------------------------------------------------------------------------

_ALLOWED_SCOPES: frozenset[int] = frozenset({1, 2, 3})
_ALLOWED_SUB_SCOPES: frozenset[str] = frozenset({
    "combustion", "process", "fugitive",
    "LB", "MB",
    "Cat1", "Cat2",
    "Cat3_WTT_FUEL", "Cat3_WTT_ELEC", "Cat3_TND",
    "Cat4", "Cat5", "Cat6", "Cat7",
    "Cat8_ZERO", "Cat9", "Cat10_ZERO", "Cat11_ZERO",
    "Cat12", "Cat13_ZERO", "Cat14_ZERO", "Cat15_ZERO",
})
_ALLOWED_GWP_SETS: frozenset[str] = frozenset({"AR6", "AR5"})
_ALLOWED_REG_STREAMS: frozenset[str] = frozenset({"CSRD_ESRS_E1", "EU_ETS_PHASE_IV"})
_ALLOWED_METHODOLOGIES: frozenset[str] = frozenset({
    "activity-based", "mass-based", "spend-based",
    "distance-based", "stoichiometric", "declared-zero",
    "location-based", "market-based",
})
_ALLOWED_CODICE_SITO: frozenset[str] = frozenset({
    "IANO", "VIANO", "VIANO_GARGOLA", "CASALGRANDE",
    "FIORANO", "SASSUOLO", "FRASSINORO",
})
_ALLOWED_REPORTING_YEARS: frozenset[int] = frozenset(range(2020, 2100))

GwpSetLiteral = Literal["AR6", "AR5"]
RegStreamLiteral = Literal["CSRD_ESRS_E1", "EU_ETS_PHASE_IV"]


# ---------------------------------------------------------------------------
# Read / response model
# ---------------------------------------------------------------------------


class EmissionResponse(BaseModel):
    """Full emission row as returned by GET /emissions.

    Mirrors all columns in ``calc.emissions_consolidated`` (FR-22, ADR-007).

    Attributes:
        id: Primary key UUID.
        correlation_id: Run-level UUID linking all rows from a batch.
        raw_row_id: FK back to the originating raw ingestion row.
        raw_scope: Scope of the raw row (1, 2, or 3).
        scope: Emission scope (1, 2, or 3).
        sub_scope: Sub-scope identifier (e.g. 'combustion', 'LB', 'Cat1').
        codice_sito: 7-site code or None for corporate-level rows.
        anno: Reporting year.
        tco2e: Total tonnes CO2-equivalent.
        co2_tonne: Direct CO2 mass in tonnes (optional).
        ch4_tco2e: CH4 contribution in tCO2e (optional).
        n2o_tco2e: N2O contribution in tCO2e (optional).
        co2_biogenic_tonne: Biogenic CO2 memo (ADR-007; not included in tco2e).
        co2_fossil_tonne: Fossil CO2 component (ADR-007).
        factor_id: Factor catalog UUID FK.
        factor_version: Version tag of the factor used.
        factor_source: Provider (DEFRA / ISPRA / ecoinvent / IPCC …).
        gwp_set: GWP set used ('AR6' or 'AR5').
        methodology: Calculation methodology.
        regulatory_stream: 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.
        calc_timestamp: UTC timestamp of the calculation run.
        created_by: Username or service account.
        valid_from: Row activation timestamp (UTC).
        valid_to: Supersession timestamp (None if active).
        superseded_by: UUID of the replacement row in the correction chain.
        reason_code: Correction reason code (FR-21).
        disclosure_notes: Free-text narrative (FR-18, FR-35, FR-36).
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    correlation_id: UUID
    raw_row_id: UUID | None
    raw_scope: int
    scope: int
    sub_scope: str
    codice_sito: str | None
    anno: int
    tco2e: float
    co2_tonne: float | None = None
    ch4_tco2e: float | None = None
    n2o_tco2e: float | None = None
    co2_biogenic_tonne: float | None = None
    co2_fossil_tonne: float | None = None
    factor_id: UUID
    factor_version: str
    factor_source: str
    gwp_set: GwpSetLiteral
    methodology: str
    regulatory_stream: RegStreamLiteral
    calc_timestamp: datetime
    created_by: str
    valid_from: datetime
    valid_to: datetime | None = None
    superseded_by: UUID | None = None
    reason_code: str | None = None
    disclosure_notes: str | None = None


# ---------------------------------------------------------------------------
# Write / create model
# ---------------------------------------------------------------------------


class EmissionCreate(BaseModel):
    """Payload for ``POST /api/v1/emissions`` (append-only, FR-30).

    Server auto-fills: ``id``, ``calc_timestamp``, ``created_by``,
    ``valid_from``, ``correlation_id`` (from request header/middleware).
    Client must supply all other mandatory provenance fields.

    Attributes:
        scope: Emission scope — 1, 2, or 3.
        sub_scope: Sub-scope label validated against the allowed vocabulary.
        codice_sito: Site code (required for Scope 1 and 2; optional for S3).
        anno: Reporting year (2020–2099).
        tco2e: Non-negative tCO2e value.
        co2_tonne: Direct CO2 mass (optional).
        ch4_tco2e: CH4 contribution in tCO2e (optional).
        n2o_tco2e: N2O contribution in tCO2e (optional).
        co2_biogenic_tonne: Biogenic CO2 memo (ADR-007).
        co2_fossil_tonne: Fossil CO2 component (ADR-007).
        raw_row_id: UUID of the originating raw ingestion row.
        raw_scope: Scope of the raw row.
        factor_id: UUID referencing ref.factor_catalog.id.
        factor_version: Exact version string of the factor used.
        factor_source: Provider identifier.
        gwp_set: 'AR6' (CSRD default) or 'AR5' (EU ETS dual-track).
        methodology: Calculation methodology.
        regulatory_stream: Regulatory context tag.
        disclosure_notes: Optional ESRS narrative.
        reason_code: Omitted on new rows; present only in the correction flow.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: int = Field(ge=1, le=3)
    sub_scope: str = Field(min_length=1, max_length=40)
    codice_sito: str | None = Field(default=None, max_length=40)
    anno: int = Field(ge=2020, le=2099)
    tco2e: Annotated[float, Field(ge=0.0)]
    co2_tonne: Annotated[float, Field(ge=0.0)] | None = None
    ch4_tco2e: Annotated[float, Field(ge=0.0)] | None = None
    n2o_tco2e: Annotated[float, Field(ge=0.0)] | None = None
    co2_biogenic_tonne: Annotated[float, Field(ge=0.0)] | None = None
    co2_fossil_tonne: Annotated[float, Field(ge=0.0)] | None = None
    raw_row_id: UUID | None = None
    raw_scope: int = Field(ge=1, le=3, default=1)
    factor_id: UUID
    factor_version: str = Field(min_length=1, max_length=40)
    factor_source: str = Field(min_length=1, max_length=40)
    gwp_set: GwpSetLiteral
    methodology: str = Field(min_length=1, max_length=40)
    regulatory_stream: RegStreamLiteral = Field(default="CSRD_ESRS_E1")
    disclosure_notes: str | None = Field(default=None, max_length=2000)
    reason_code: str | None = None

    @field_validator("sub_scope")
    @classmethod
    def validate_sub_scope(cls, v: str) -> str:
        """Reject sub_scope values not in the allowed vocabulary.

        Args:
            v: Raw sub_scope string.

        Returns:
            Validated sub_scope string.

        Raises:
            ValueError: If sub_scope is not in the allowed set.
        """
        if v not in _ALLOWED_SUB_SCOPES:
            raise ValueError(
                f"sub_scope={v!r} is not valid. Allowed: {sorted(_ALLOWED_SUB_SCOPES)}"
            )
        return v

    @field_validator("codice_sito")
    @classmethod
    def validate_codice_sito(cls, v: str | None) -> str | None:
        """Validate site code against the 7-site allowlist.

        Args:
            v: Raw codice_sito value or None.

        Returns:
            Validated codice_sito string or None.

        Raises:
            ValueError: If a non-None value is not in the allowed set.
        """
        if v is not None and v not in _ALLOWED_CODICE_SITO:
            raise ValueError(
                f"codice_sito={v!r} not in allowed sites: {sorted(_ALLOWED_CODICE_SITO)}"
            )
        return v

    @field_validator("methodology")
    @classmethod
    def validate_methodology(cls, v: str) -> str:
        """Reject methodology strings not in the allowed vocabulary.

        Args:
            v: Raw methodology string.

        Returns:
            Validated methodology string.

        Raises:
            ValueError: If not in the allowed set.
        """
        if v not in _ALLOWED_METHODOLOGIES:
            raise ValueError(
                f"methodology={v!r} not valid. Allowed: {sorted(_ALLOWED_METHODOLOGIES)}"
            )
        return v

    @model_validator(mode="after")
    def scope_sub_scope_consistency(self) -> EmissionCreate:
        """Ensure sub_scope is valid for the given scope.

        Returns:
            Self with validated scope/sub_scope combination.

        Raises:
            ValueError: If the sub_scope does not belong to the declared scope.
        """
        scope_map: dict[int, frozenset[str]] = {
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
        allowed = scope_map.get(self.scope, frozenset())
        if self.sub_scope not in allowed:
            raise ValueError(
                f"sub_scope={self.sub_scope!r} is not valid for scope={self.scope}. "
                f"Allowed: {sorted(allowed)}"
            )
        return self


# ---------------------------------------------------------------------------
# Correction model (POST /emissions/correction)
# ---------------------------------------------------------------------------


class EmissionCorrectionCreate(BaseModel):
    """Payload for ``POST /api/v1/emissions/correction`` (FR-21).

    Inserts a new emission row and closes the predecessor via
    ``calc.fn_emit_correction``.  The ``reason_code`` must be one of the
    five approved codes defined in the DB stored procedure.

    Attributes:
        supersedes_id: UUID of the active emission row to supersede.
        new_record: The replacement emission data.
        reason_code: Why the correction is being made.
        justification: Human-readable explanation (min 10 chars, ISAE 3000 trail).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    supersedes_id: UUID
    new_record: EmissionCreate
    reason_code: Literal[
        "DATA_ERROR",
        "FACTOR_UPDATE",
        "BOUNDARY_CHANGE",
        "METHODOLOGY_REVISION",
        "RESTATEMENT_>5PCT",
    ]
    justification: str = Field(min_length=10, max_length=1000)


class EmissionCorrectionResponse(BaseModel):
    """Response for a successful correction operation.

    Attributes:
        new_id: UUID of the newly created replacement row.
        supersedes_id: UUID of the row that was closed.
        correlation_id: Request correlation UUID.
    """

    model_config = ConfigDict(frozen=True)

    new_id: UUID
    supersedes_id: UUID
    correlation_id: UUID


# ---------------------------------------------------------------------------
# Filter / query params
# ---------------------------------------------------------------------------


class EmissionFilter(BaseModel):
    """Query parameters for ``GET /api/v1/emissions``.

    All fields are optional; omitting a field means no filter on that column.

    Attributes:
        scope: Filter by scope (1, 2, or 3).
        anno: Filter by reporting year.
        codice_sito: Filter by site code.
        sub_scope: Filter by sub-scope label.
        regulatory_stream: Filter by regulatory stream.
        gwp_set: Filter by GWP set.
        cursor: Opaque pagination cursor from previous response.
        limit: Page size (1–500, default 50).
    """

    model_config = ConfigDict(extra="forbid")

    scope: int | None = Field(default=None, ge=1, le=3)
    anno: int | None = Field(default=None, ge=2020, le=2099)
    codice_sito: str | None = Field(default=None, max_length=40)
    sub_scope: str | None = Field(default=None, max_length=40)
    regulatory_stream: RegStreamLiteral | None = None
    gwp_set: GwpSetLiteral | None = None
    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=500)

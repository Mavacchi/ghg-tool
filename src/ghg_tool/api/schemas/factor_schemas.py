"""Pydantic v2 schemas for /factor-catalog endpoints (FR-04, MG-01/02)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_ALLOWED_SOURCES = frozenset({
    "DEFRA", "ISPRA", "IEA", "ecoinvent", "EXIOBASE",
    "CDP", "IPCC", "AIB", "EPD", "GHGProtocol",
})

GwpSetLiteral = Literal["AR6", "AR5", "n/a"]


class FactorCatalogResponse(BaseModel):
    """Response schema for a factor catalog entry.

    Attributes:
        id: Primary key UUID.
        factor_id: String factor identifier (e.g. 'WTT_GAS_NAT_DEFRA_2025').
        version: Version tag.
        substance: Substance or material described.
        scope: Applicable scope (1, 2, or 3).
        category: Category label (e.g. 'Cat1', 'LB', 'combustion').
        source: Provider identifier.
        value: Numeric factor value (None for licence-restricted entries).
        is_licence_only: True when value cannot be republished.
        is_tbc: True when factor is pending numeric pinning (OI-9).
        unit: Unit string (e.g. 'kgCO2e/kWh').
        gwp_set: GWP set ('AR6', 'AR5', or 'n/a' for GWP-independent factors).
        vintage: Publication year of the source document.
        valid_from: Date from which this factor version is valid.
        valid_to: Date on which this version was superseded (None if current).
        applicability_note: Free-text applicability description.
        pdf_source_uri: Object-store path to the source PDF.
        published_at: Timestamp when this version was published.
        published_by: Username who published it.
        is_published: False until explicitly published; immutable after.
        biogenic_co2_kg_per_unit: Companion biogenic CO2 value (ADR-007).
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    factor_id: str
    version: str
    substance: str
    scope: int
    category: str
    source: str
    value: float | None = None
    is_licence_only: bool
    is_tbc: bool
    unit: str
    gwp_set: GwpSetLiteral
    vintage: str | None = None
    valid_from: date
    valid_to: date | None = None
    applicability_note: str | None = None
    pdf_source_uri: str | None = None
    published_at: datetime
    published_by: str
    is_published: bool
    biogenic_co2_kg_per_unit: float | None = None


class FactorCatalogCreate(BaseModel):
    """Payload for ``POST /api/v1/factor-catalog`` (data_steward only).

    Creates a NEW version of a factor entry.  Pre-published factors may
    have ``value=None`` when licence restrictions apply.  Once published,
    the DB trigger makes the row immutable (MG-02).

    Attributes:
        factor_id: String identifier for this factor (new or existing).
        version: Version label (must be unique within the factor_id + gwp_set).
        substance: Substance or material being characterised.
        scope: Applicable emission scope.
        category: Category label.
        source: Provider from the approved list.
        value: Numeric factor value (optional for licence-only entries).
        is_licence_only: Mark as licence-only if value cannot be republished.
        unit: Measurement unit.
        gwp_set: GWP set or 'n/a' for GWP-independent factors.
        vintage: Publication vintage year string.
        valid_from: Date from which this version applies.
        applicability_note: Optional note on scope of applicability.
        pdf_source_uri: Object-store URI of the source document.
        biogenic_co2_kg_per_unit: Biogenic CO2 companion value (ADR-007).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    factor_id: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=40)
    substance: str = Field(min_length=1, max_length=100)
    scope: int = Field(ge=1, le=3)
    category: str = Field(min_length=1, max_length=40)
    source: str = Field(min_length=1, max_length=40)
    value: float | None = Field(default=None, ge=0.0)
    is_licence_only: bool = False
    unit: str = Field(min_length=1, max_length=40)
    gwp_set: GwpSetLiteral
    vintage: str | None = Field(default=None, max_length=40)
    valid_from: date
    applicability_note: str | None = Field(default=None, max_length=2000)
    pdf_source_uri: str | None = Field(default=None, max_length=512)
    biogenic_co2_kg_per_unit: float | None = Field(default=None, ge=0.0)

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        """Reject source values outside the approved provider list.

        Args:
            v: Raw source string.

        Returns:
            Validated source string.

        Raises:
            ValueError: If source is not in the allowed set.
        """
        if v not in _ALLOWED_SOURCES:
            raise ValueError(
                f"source={v!r} not in allowed providers: {sorted(_ALLOWED_SOURCES)}"
            )
        return v

    @field_validator("factor_id")
    @classmethod
    def validate_factor_id_format(cls, v: str) -> str:
        """Validate factor_id is uppercase alphanumeric with underscores/hyphens.

        Args:
            v: Raw factor_id string.

        Returns:
            Validated factor_id string.

        Raises:
            ValueError: If format is invalid.
        """
        clean = v.replace("_", "").replace("-", "")
        if not clean.isalnum():
            raise ValueError("factor_id must be alphanumeric (underscores and hyphens allowed)")
        return v


class FactorCatalogPublishRequest(BaseModel):
    """Optional body for ``POST /api/v1/factor-catalog/{factor_uuid}/publish``.

    The body is fully optional — the endpoint can be called with an empty
    payload.  When provided, ``publish_notes`` is recorded in the structured
    audit log entry.

    Attributes:
        publish_notes: Free-text note recorded for audit purposes (max 500 chars).
    """

    model_config = ConfigDict(extra="forbid")

    publish_notes: str | None = Field(default=None, max_length=500)


class FactorCatalogPublishResponse(FactorCatalogResponse):
    """Response schema for a successful publish operation.

    Extends ``FactorCatalogResponse`` with no additional fields — the full
    updated row is returned so the client sees ``is_published=True``,
    ``published_by``, and ``published_at`` in one response.

    NOTE (follow-up MG-03): ``published_at`` currently reflects the row
    INSERT timestamp (DB DEFAULT now()) because the column is ``NOT NULL
    DEFAULT now()`` and is set on draft creation.  After this publish call
    the column is overwritten with the actual publish time, so the returned
    value IS the true publish timestamp.  However, for rows created before
    this endpoint existed the draft ``published_at`` was already set to the
    creation time and was NOT meaningful as a "published" timestamp.  A future
    migration should add a separate ``created_at`` column so the two events
    can be tracked independently.
    """


class FactorFilter(BaseModel):
    """Query parameters for ``GET /api/v1/factor-catalog``.

    Attributes:
        scope: Filter by applicable scope.
        source: Filter by provider.
        gwp_set: Filter by GWP set.
        is_published: Filter by publish status.
        factor_id: Filter by factor string identifier.
        cursor: Pagination cursor.
        limit: Page size (1–200, default 50).
    """

    model_config = ConfigDict(extra="forbid")

    scope: int | None = Field(default=None, ge=1, le=3)
    source: str | None = Field(default=None, max_length=40)
    gwp_set: GwpSetLiteral | None = None
    is_published: bool | None = None
    factor_id: str | None = Field(default=None, max_length=80)
    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=200)

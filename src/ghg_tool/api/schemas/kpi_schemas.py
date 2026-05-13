"""Pydantic v2 schemas for /kpis and /audit-trail endpoints (FR-29, FR-22).

Wave 3 visualization depends on these typed schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# KPI schemas
# ---------------------------------------------------------------------------


class KpiRow(BaseModel):
    """A single KPI row from calc.mv_kpi_summary.

    All fields are optional because the MV schema may evolve; unknown columns
    from the DB are passed through via ``extra="allow"`` at the row level so
    that the response is forward-compatible with wave 3 additions.

    Attributes:
        scope: Emission scope (1, 2, or 3).
        sub_scope: Sub-scope label.
        codice_sito: Site code.
        anno: Reporting year.
        gwp_set: GWP set used.
        tco2e: Total tCO2e for this aggregation bucket.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True, extra="allow")

    scope: int | None = None
    sub_scope: str | None = None
    codice_sito: str | None = None
    anno: int | None = None
    gwp_set: str | None = None
    tco2e: float | None = None


class KpiSummaryResponse(BaseModel):
    """Response for ``GET /api/v1/kpis``.

    Attributes:
        kpis: List of KPI rows from calc.mv_kpi_summary.
        gwp_set: GWP set used for the query.
        correlation_id: Request correlation UUID (FR-22).
        as_of: UTC timestamp of the query.
        note: Optional note (e.g. when MV is not yet available).
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    kpis: list[Any] = Field(default_factory=list)
    gwp_set: str
    correlation_id: str
    as_of: datetime
    note: str | None = Field(default=None, alias="_note")

    model_config = ConfigDict(
        from_attributes=True,
        frozen=True,
        populate_by_name=True,
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Override model_dump to serialise ``note`` as ``_note`` in JSON output."""
        data = super().model_dump(**kwargs)
        if "note" in data and data["note"] is not None:
            data["_note"] = data.pop("note")
        elif "note" in data:
            data.pop("note")
        return data


# ---------------------------------------------------------------------------
# Audit trail schemas
# ---------------------------------------------------------------------------


class AuditTrailEntry(BaseModel):
    """A single row in the audit trail response.

    Mirrors the columns from the inline SQL query in audit_trail router.
    All fields nullable to handle LEFT JOINs.

    Attributes:
        emission_id: UUID of the emission row.
        correlation_id: Run-level UUID.
        scope: Emission scope.
        sub_scope: Sub-scope label.
        codice_sito: Site code.
        anno: Reporting year.
        tco2e: Total tCO2e.
        gwp_set: GWP set.
        methodology: Calculation methodology.
        regulatory_stream: Regulatory stream tag.
        calc_timestamp: UTC timestamp of the calc run.
        created_by: Username or service account.
        factor_source: Factor source provider.
        factor_version: Factor version tag.
        valid_from: Row activation timestamp.
        valid_to: Supersession timestamp (None if active).
        superseded_by: UUID of the replacement row.
        reason_code: Correction reason code.
        raw_row_id: FK to raw ingestion row.
        factor_string_id: String factor identifier.
        factor_provider: Factor provider name.
        factor_gwp_set: GWP set on the factor row.
        factor_value: Numeric factor value.
        factor_unit: Factor unit string.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    emission_id: str | None = None
    correlation_id: str | None = None
    scope: int | None = None
    sub_scope: str | None = None
    codice_sito: str | None = None
    anno: int | None = None
    tco2e: float | None = None
    gwp_set: str | None = None
    methodology: str | None = None
    regulatory_stream: str | None = None
    calc_timestamp: str | None = None
    created_by: str | None = None
    factor_source: str | None = None
    factor_version: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    superseded_by: str | None = None
    reason_code: str | None = None
    raw_row_id: str | None = None
    factor_string_id: str | None = None
    factor_provider: str | None = None
    factor_gwp_set: str | None = None
    factor_value: float | None = None
    factor_unit: str | None = None


class PaginationMeta(BaseModel):
    """Pagination metadata for list responses.

    Attributes:
        count: Number of rows in this page.
        next_cursor: Cursor for the next page (None if last page).
    """

    model_config = ConfigDict(frozen=True)

    count: int
    next_cursor: str | None = None


class AuditTrailResponse(BaseModel):
    """Response for ``GET /api/v1/audit-trail``.

    Attributes:
        entries: List of audit trail rows.
        pagination: Pagination metadata.
        correlation_id: Request correlation UUID (FR-22).
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    entries: list[AuditTrailEntry]
    pagination: PaginationMeta
    correlation_id: str


# ---------------------------------------------------------------------------
# Emission create response
# ---------------------------------------------------------------------------


class EmissionCreateResponse(BaseModel):
    """Response for ``POST /api/v1/emissions`` (append-only create).

    Attributes:
        id: UUID of the newly created emission row.
        correlation_id: Request correlation UUID.
        created_at: UTC timestamp of creation.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    correlation_id: str
    created_at: datetime

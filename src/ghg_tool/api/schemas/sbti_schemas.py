"""Pydantic v2 schemas for /api/v1/sbti endpoints (ESRS E1-4).

All enums mirror the frozensets in ``ghg_tool.domain.entities.sbti_target``
so that the API surface validates identically to the domain invariants.

Decimal is used end-to-end for tco2e values (no float drift in JSON responses).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Allowed value sets -- must stay in sync with domain entity frozensets
# ---------------------------------------------------------------------------
_ALLOWED_SCOPES: frozenset[str] = frozenset({
    "S1", "S2_LB", "S2_MB", "S3",
    "S1+S2_LB", "S1+S2_MB",
    "S1+S2_MB+S3",
})

_ALLOWED_ALIGNMENT: frozenset[str] = frozenset({"1.5C", "WB2C", "2C"})

_ALLOWED_METHODOLOGIES: frozenset[str] = frozenset({
    "SBTi_ACA", "SDA", "GEVA", "SBTi_NetZero",
    "supplier_engagement", "custom",
})

_ALLOWED_SBTI_STATUS: frozenset[str] = frozenset({
    "none", "committed", "targets_set", "validated",
})


class SbtiTargetCreate(BaseModel):
    """Request body for POST /api/v1/sbti/targets.

    Validates all SBTi and ESRS E1-4 invariants. The ``tenant_id`` field is
    intentionally absent: it is derived from the JWT claim and injected by
    the handler (never trusted from the request body).

    Attributes:
        name: Human-readable label (max 200 chars).
        scope_coverage: Scope mix key from the SBTi-allowed set.
        baseline_year: First year on the trajectory (2000-2100).
        baseline_tco2e: Positive emissions at baseline_year.
        target_year: Final year (must be > baseline_year).
        target_tco2e: Target emissions (0 <= target_tco2e <= baseline_tco2e).
        alignment: Climate alignment label.
        methodology: Methodology label.
        sbti_approval_status: External SBTi validation status.
        sbti_validation_date: Required when sbti_approval_status == 'validated'.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Annotated[str, Field(min_length=1, max_length=200)]
    scope_coverage: str
    baseline_year: Annotated[int, Field(ge=2000, le=2100)]
    baseline_tco2e: Annotated[Decimal, Field(gt=Decimal("0"))]
    target_year: Annotated[int, Field(ge=2001, le=2100)]
    target_tco2e: Annotated[Decimal, Field(ge=Decimal("0"))]
    alignment: str
    methodology: str
    sbti_approval_status: str
    sbti_validation_date: date | None = None

    @model_validator(mode="after")
    def _validate_domain_invariants(self) -> "SbtiTargetCreate":
        """Mirror the SbtiTarget.__post_init__ invariants at the API boundary."""
        if self.scope_coverage not in _ALLOWED_SCOPES:
            raise ValueError(
                f"scope_coverage={self.scope_coverage!r} is not valid; "
                f"allowed: {sorted(_ALLOWED_SCOPES)}"
            )
        if self.alignment not in _ALLOWED_ALIGNMENT:
            raise ValueError(
                f"alignment={self.alignment!r} is not valid; "
                f"allowed: {sorted(_ALLOWED_ALIGNMENT)}"
            )
        if self.methodology not in _ALLOWED_METHODOLOGIES:
            raise ValueError(
                f"methodology={self.methodology!r} is not valid; "
                f"allowed: {sorted(_ALLOWED_METHODOLOGIES)}"
            )
        if self.sbti_approval_status not in _ALLOWED_SBTI_STATUS:
            raise ValueError(
                f"sbti_approval_status={self.sbti_approval_status!r} is not valid; "
                f"allowed: {sorted(_ALLOWED_SBTI_STATUS)}"
            )
        if self.target_year <= self.baseline_year:
            raise ValueError("target_year must be after baseline_year")
        if self.target_tco2e > self.baseline_tco2e:
            raise ValueError(
                "target_tco2e must not exceed baseline_tco2e "
                "(this is a REDUCTION target)"
            )
        if self.sbti_approval_status == "validated" and self.sbti_validation_date is None:
            raise ValueError(
                "sbti_validation_date is required when sbti_approval_status is 'validated'"
            )
        return self


class SbtiTargetResponse(BaseModel):
    """Response body for a single SBTi target.

    Attributes:
        target_id: UUID primary key.
        tenant_id: Owning tenant UUID.
        name: Human-readable label.
        scope_coverage: Scope mix key.
        baseline_year: First year on the trajectory.
        baseline_tco2e: Emissions at baseline year.
        target_year: Final year on the trajectory.
        target_tco2e: Target emissions.
        reduction_pct: Percentage reduction stored for query convenience.
        alignment: Climate alignment label.
        methodology: Methodology label.
        sbti_approval_status: External SBTi validation status.
        sbti_validation_date: Date of SBTi validation (nullable).
        created_by: User UUID string.
        created_at: ISO-8601 creation timestamp.
        is_active: Whether this target is currently active.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    target_id: UUID
    tenant_id: UUID
    name: str
    scope_coverage: str
    baseline_year: int
    baseline_tco2e: Decimal
    target_year: int
    target_tco2e: Decimal
    reduction_pct: Decimal
    alignment: str
    methodology: str
    sbti_approval_status: str
    sbti_validation_date: date | None
    created_by: str
    created_at: datetime
    is_active: bool


class TrajectoryPointResponse(BaseModel):
    """One point on the SBTi linear trajectory.

    Attributes:
        year: Calendar year.
        trajectory_tco2e: Straight-line target value at this year.
        actual_tco2e: Observed consolidated emissions for this year, or None.
    """

    model_config = ConfigDict(frozen=True)

    year: int
    trajectory_tco2e: Decimal
    actual_tco2e: Decimal | None = None


class TrajectoryResponse(BaseModel):
    """Response body for GET /api/v1/sbti/targets/{uuid}/trajectory.

    Attributes:
        target: The SBTi target metadata.
        status: Traffic-light status (ON_TRACK / SLIGHTLY_OFF / OFF_TRACK / NO_DATA).
        trajectory: List of trajectory + actual points, baseline to target year.
    """

    model_config = ConfigDict(frozen=True)

    target: SbtiTargetResponse
    status: str
    trajectory: list[TrajectoryPointResponse]

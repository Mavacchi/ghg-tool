"""SbtiTarget domain entity for ESRS E1-4 disclosure.

A target captures the science-based GHG reduction the organisation
commits to for a given scope coverage. The dataclass is frozen so
amendments must go through a new active row + a deactivation of the
old one - never an in-place edit (mirrors the append-only ledger
philosophy used elsewhere).

Normative reference:
  - ESRS E1-4 AR §34-37 (target attributes that must be disclosed).
  - SBTi Corporate Net-Zero Standard v1.2 (2024) - methodology field
    enumerated values: SBTi (ACA), SDA, GEVA, custom.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

_ALLOWED_SCOPES: Final[frozenset[str]] = frozenset({
    "S1", "S2_LB", "S2_MB", "S3",
    "S1+S2_LB", "S1+S2_MB",
    "S1+S2_MB+S3",
})

_ALLOWED_ALIGNMENT: Final[frozenset[str]] = frozenset({
    "1.5C", "WB2C", "2C",
})

_ALLOWED_METHODOLOGIES: Final[frozenset[str]] = frozenset({
    "SBTi_ACA", "SDA", "GEVA", "SBTi_NetZero",
    "supplier_engagement", "custom",
})

_ALLOWED_SBTI_STATUS: Final[frozenset[str]] = frozenset({
    "none", "committed", "targets_set", "validated",
})


@dataclass(frozen=True, slots=True)
class SbtiTarget:
    """A single SBTi-aligned reduction target.

    Attributes:
        target_id: Primary-key UUID.
        tenant_id: Tenant UUID for multi-tenant isolation.
        name: Human-readable label (e.g. "Near-term Scope 1+2 -42%").
        scope_coverage: Allowed scope-mix value (see _ALLOWED_SCOPES).
        baseline_year: First year of the trajectory.
        baseline_tco2e: Emissions at baseline_year (Decimal).
        target_year: Last year of the trajectory.
        target_tco2e: Emissions at target_year (Decimal).
        reduction_pct: Percentage reduction from baseline (computed,
            stored for query convenience).
        alignment: Climate alignment label.
        methodology: Methodology label.
        sbti_approval_status: SBTi external validation status.
        sbti_validation_date: Date of SBTi validation, if validated.
        created_by: User UUID string.
        created_at: Creation timestamp.
        is_active: Only one active target per scope_coverage per tenant.
    """

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
    is_active: bool = True

    def __post_init__(self) -> None:
        """Enforce SBTi + ESRS E1-4 invariants at construction time."""
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
        if self.baseline_tco2e <= 0:
            raise ValueError("baseline_tco2e must be positive")
        if self.target_tco2e < 0:
            raise ValueError("target_tco2e must be non-negative")
        if self.target_tco2e > self.baseline_tco2e:
            raise ValueError(
                "target_tco2e must not exceed baseline_tco2e "
                "(this is a REDUCTION target)"
            )
        if (
            self.sbti_approval_status == "validated"
            and self.sbti_validation_date is None
        ):
            raise ValueError(
                "sbti_validation_date is required when status is 'validated'"
            )

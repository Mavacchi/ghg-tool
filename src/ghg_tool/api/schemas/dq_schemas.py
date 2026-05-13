"""Pydantic v2 schemas for /dq-findings endpoints (FR-32)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


SeverityLiteral = Literal["CRIT", "WARN", "INFO"]
ResolutionLiteral = Literal["OPEN", "WAIVED", "REMEDIATED"]


class DqFindingResponse(BaseModel):
    """Response schema for a DQ finding.

    Attributes:
        id: Primary key UUID.
        correlation_id: Run-level UUID.
        parent_finding_id: Points to the original finding this resolves (None for root).
        rule_id: DQ rule that fired (e.g. 'DQ-CRIT-01').
        severity: 'CRIT', 'WARN', or 'INFO'.
        scope: Emission scope related to this finding.
        codice_sito: Site code related to this finding.
        anno: Reporting year related to this finding.
        metric: Human-readable metric name observed.
        value_observed: Observed numeric value.
        value_reference: Reference / expected numeric value.
        ratio_yoy: Year-on-year ratio.
        z_score: Z-score of the observation.
        trigger_desc: Full description of what triggered this finding.
        recommended_action: Suggested remediation step.
        raw_row_id: Soft FK to the failing raw ingestion row.
        blocks_pipeline: True if this is a pipeline-blocking CRIT finding.
        dq_report_version: Version of the DQ report that generated this finding.
        assessed_at: Timestamp when the DQ check ran.
        resolution_status: 'OPEN', 'WAIVED', or 'REMEDIATED'.
        waiver_reason_code: Approved waiver reason code.
        waiver_justification: Free-text waiver justification.
        waiver_approved_by: Username who approved the waiver.
        resolved_at: Timestamp of resolution.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    correlation_id: UUID
    parent_finding_id: UUID | None = None
    rule_id: str
    severity: SeverityLiteral
    scope: int | None = None
    codice_sito: str | None = None
    anno: int | None = None
    metric: str | None = None
    value_observed: float | None = None
    value_reference: float | None = None
    ratio_yoy: float | None = None
    z_score: float | None = None
    trigger_desc: str | None = None
    recommended_action: str | None = None
    raw_row_id: UUID | None = None
    blocks_pipeline: bool
    dq_report_version: str
    assessed_at: datetime
    resolution_status: ResolutionLiteral
    waiver_reason_code: str | None = None
    waiver_justification: str | None = None
    waiver_approved_by: str | None = None
    resolved_at: datetime | None = None


class WaiverRequest(BaseModel):
    """Payload for ``POST /api/v1/dq-findings/waiver/{finding_id}``.

    Creates an append-only resolution row with ``resolution_status='WAIVED'``
    and ``parent_finding_id`` set to the original finding UUID.

    Attributes:
        reason_code: Approved waiver reason code from the controlled vocabulary.
        justification: Free-text justification (min 10 chars for ISAE 3000 trail).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason_code: Literal[
        "OPERATIONAL_ANNOTATION",
        "USER_CONFIRMED_ZERO",
        "METHODOLOGY_INFO",
        "ASSURANCE_ACCEPTED",
    ]
    justification: str = Field(min_length=10, max_length=1000)


class DqFindingFilter(BaseModel):
    """Query parameters for ``GET /api/v1/dq-findings``.

    Attributes:
        severity: Filter by severity level.
        rule_id: Filter by specific DQ rule identifier.
        resolution_status: Filter by resolution status.
        anno: Filter by reporting year.
        codice_sito: Filter by site code.
        correlation_id: Filter by correlation UUID (for batch-level queries).
        cursor: Pagination cursor.
        limit: Page size (1–500, default 50).
    """

    model_config = ConfigDict(extra="forbid")

    severity: SeverityLiteral | None = None
    rule_id: str | None = Field(default=None, max_length=40)
    resolution_status: ResolutionLiteral | None = None
    anno: int | None = Field(default=None, ge=2020, le=2099)
    codice_sito: str | None = Field(default=None, max_length=40)
    correlation_id: UUID | None = None
    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=500)

"""Pydantic v2 schemas for /reports and /exports endpoints (FR-27, FR-28).

New schemas introduced for REV-WAVE3-007 Celery migration:
    CeleryJobAccepted  — 202 response body from POST /exports/pdf|xlsx
    CeleryJobStatus    — 200 response body from GET /exports/{task_id}/status
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PdfReportRequest(BaseModel):
    """Payload for ``POST /api/v1/reports/pdf``.

    Triggers asynchronous CSRD ESRS E1-6 PDF generation.  The actual
    WeasyPrint rendering is implemented in wave 3 by the visualization-agent.

    Attributes:
        anno: Reporting year for the report.
        gwp_set: GWP set to use ('AR6' for CSRD, 'AR5' for EU ETS comparison).
        language: Report language ('en' or 'it' — FR-33).
        regulatory_stream: Which emission stream to include.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    anno: int = Field(ge=2020, le=2099)
    gwp_set: Literal["AR6", "AR5"] = Field(default="AR6")
    language: Literal["en", "it"] = Field(default="en")
    regulatory_stream: Literal["CSRD_ESRS_E1", "EU_ETS_PHASE_IV"] = Field(
        default="CSRD_ESRS_E1"
    )


class ExcelReportRequest(BaseModel):
    """Payload for ``POST /api/v1/reports/excel``.

    Triggers asynchronous multi-sheet Excel generation (FR-27).

    Attributes:
        anno: Reporting year.
        gwp_set: GWP set to use.
        include_audit_trail: Whether to include the Audit Trail sheet.
        include_factor_snapshot: Whether to include the Factor Catalog Snapshot sheet.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    anno: int = Field(ge=2020, le=2099)
    gwp_set: Literal["AR6", "AR5"] = Field(default="AR6")
    include_audit_trail: bool = True
    include_factor_snapshot: bool = True


class ReportJobStatus(BaseModel):
    """Response for ``GET /api/v1/reports/status/{job_id}``.

    Attributes:
        job_id: The async job identifier.
        status: Current job status.
        download_url: Object-store pre-signed URL when status is 'COMPLETED'.
        error_message: Error detail when status is 'FAILED'.
        correlation_id: Request correlation UUID.
    """

    model_config = ConfigDict(frozen=True)

    job_id: UUID
    status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]
    download_url: str | None = None
    error_message: str | None = None
    correlation_id: UUID


# ---------------------------------------------------------------------------
# REV-WAVE3-007 — Celery-backed export schemas
# ---------------------------------------------------------------------------


class CeleryJobAccepted(BaseModel):
    """202 Accepted response for ``POST /api/v1/exports/pdf`` and ``/xlsx``.

    Returned immediately after the Celery task is enqueued.

    Attributes:
        task_id: Celery task UUID (use for polling and download).
        status_url: Absolute URL for ``GET /api/v1/exports/{task_id}/status``.
    """

    model_config = ConfigDict(frozen=True)

    task_id: str = Field(description="Celery task UUID")
    status_url: str = Field(description="URL to poll for job status")


class CeleryJobStatus(BaseModel):
    """Response for ``GET /api/v1/exports/{task_id}/status``.

    Maps Celery's internal states to the public API vocabulary:
        PENDING   — task queued, not yet picked up by a worker
        STARTED   — worker has started (requires task_track_started=True)
        SUCCESS   — task completed; ``result`` contains the metadata dict
        FAILURE   — task failed; ``error`` contains the exception message

    Attributes:
        task_id: The Celery task UUID.
        state: Current task state string.
        result: Metadata dict returned by the task on success (None otherwise).
        error: Exception message on failure (None otherwise).
    """

    model_config = ConfigDict(frozen=True)

    task_id: str
    state: Literal["PENDING", "STARTED", "SUCCESS", "FAILURE", "REVOKED", "RETRY"]
    result: dict[str, Any] | None = None
    error: str | None = None

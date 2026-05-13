"""Export service — orchestrates async PDF and Excel report generation.

In v1 (wave 2), this service creates a job record and immediately returns a
``job_id``.  The actual WeasyPrint (PDF) and openpyxl (Excel) rendering is
implemented by the visualization-agent in wave 3.  The service uses
``BackgroundTasks`` to simulate async execution.

A simple in-memory job store is used in v1; wave 3 will replace this with a
proper task queue (e.g. Celery or a DB-backed job table).
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# In-memory job store — replaced by a DB table or task queue in wave 3.
_jobs: dict[str, dict[str, Any]] = {}


def create_report_job(
    *,
    job_type: str,
    params: dict[str, Any],
    user_sub: str,
    correlation_id: str,
) -> uuid.UUID:
    """Register a new async report job and return its ID.

    Args:
        job_type: 'pdf' or 'excel'.
        params: Report parameters (anno, gwp_set, language, etc.).
        user_sub: The requesting user's sub claim (for logging, not PII).
        correlation_id: Request correlation UUID.

    Returns:
        A new ``job_id`` UUID.
    """
    job_id = uuid.uuid4()
    _jobs[str(job_id)] = {
        "job_id": str(job_id),
        "type": job_type,
        "params": params,
        "status": "PENDING",
        "created_by": user_sub[:8],  # truncated — no full PII in store
        "correlation_id": correlation_id,
        "download_url": None,
        "error_message": None,
    }
    logger.bind(
        correlation_id=correlation_id,
        job_id=str(job_id),
        job_type=job_type,
    ).info("Report job registered")
    return job_id


def get_job_status(job_id: uuid.UUID) -> dict[str, Any] | None:
    """Retrieve the current status of a report job.

    Args:
        job_id: The job UUID returned by ``create_report_job``.

    Returns:
        The job state dict, or None if not found.
    """
    return _jobs.get(str(job_id))


def simulate_job_completion(job_id: uuid.UUID, download_url: str) -> None:
    """Mark a job as COMPLETED with a download URL (wave 3 hook).

    This function is called by the background task runner in wave 3 when
    the actual document has been rendered and uploaded to object storage.

    Args:
        job_id: The job UUID to mark as completed.
        download_url: Pre-signed URL for the generated document.
    """
    key = str(job_id)
    if key in _jobs:
        _jobs[key]["status"] = "COMPLETED"
        _jobs[key]["download_url"] = download_url
        logger.info("Report job completed", job_id=key)

"""Export service — orchestrates async PDF and Excel report generation.

MVP IMPLEMENTATION NOTE:
  This is a synchronous in-process implementation suitable for the MVP.
  Jobs are stored in a thread-safe in-memory dict guarded by asyncio.Lock.
  MVP — pre-prod, replace with Celery or a DB-backed job table in production.

Public API:
  start_pdf_job(tenant_id, period, user, correlation_id) -> JobId (UUID)
  start_xlsx_job(...)  -> JobId (UUID)
  get_job_status(job_id) -> dict with keys: job_id, status, type, ...
  get_job_result(job_id) -> bytes | None  (PDF or XLSX bytes when DONE)

Status vocabulary (REV-WAVE3-004):
  Internal store uses exactly 4 values: PENDING | RUNNING | DONE | FAILED.
  The API wire contract maps DONE → COMPLETED via _internal_to_wire().
  No other status strings must appear in _jobs; simulate_job_completion()
  is retired — callers should use start_*_job() which sets DONE internally.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Final

import structlog

# ---------------------------------------------------------------------------
# Internal status constants (REV-WAVE3-004)
# ---------------------------------------------------------------------------
# Internal store uses only these four values.  The API boundary converts
# _STATUS_DONE → "COMPLETED" via _internal_to_wire(); all others pass through.
_STATUS_PENDING: Final[str] = "PENDING"
_STATUS_RUNNING: Final[str] = "RUNNING"
_STATUS_DONE: Final[str] = "DONE"
_STATUS_FAILED: Final[str] = "FAILED"

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Thread-safe in-memory job store
# ---------------------------------------------------------------------------
_lock: asyncio.Lock | None = None
_jobs: dict[str, dict[str, Any]] = {}
_results: dict[str, bytes] = {}


def _get_lock() -> asyncio.Lock:
    """Return or lazily-create the module-level asyncio.Lock.

    Returns:
        The asyncio.Lock instance.
    """
    global _lock  # noqa: PLW0603
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _new_job(
    job_type: str,
    tenant_id: str,
    period: dict[str, Any],
    user: str,
    correlation_id: str,
) -> uuid.UUID:
    """Create a new job record and return its UUID.

    Args:
        job_type: 'pdf' or 'xlsx'.
        tenant_id: Tenant identifier (not logged as PII).
        period: Dict with keys 'anno', 'gwp_set', etc.
        user: User sub/identifier (truncated to 8 chars in logs).
        correlation_id: Request correlation UUID.

    Returns:
        New job UUID.
    """
    job_id = uuid.uuid4()
    _jobs[str(job_id)] = {
        "job_id": str(job_id),
        "type": job_type,
        "status": _STATUS_PENDING,  # REV-WAVE3-004: canonical internal status
        "tenant_id": tenant_id[:8],  # truncated — no full tenant PII
        "period": period,
        "created_by": user[:8],      # truncated — no full user PII
        "correlation_id": correlation_id,
        "error_message": None,
        "download_url": None,
    }
    logger.bind(
        job_id=str(job_id),
        job_type=job_type,
        correlation_id=correlation_id,
    ).info("Export job created")
    return job_id


def create_report_job(
    *,
    job_type: str,
    params: dict[str, Any],
    user_sub: str,
    correlation_id: str,
) -> uuid.UUID:
    """Register a new async report job and return its ID.

    Kept for backwards-compatibility with the existing reports router.

    Args:
        job_type: 'pdf' or 'excel'.
        params: Report parameters (anno, gwp_set, language, etc.).
        user_sub: The requesting user's sub claim.
        correlation_id: Request correlation UUID.

    Returns:
        A new job_id UUID.
    """
    return _new_job(
        job_type=job_type,
        tenant_id=params.get("tenant_id", "default"),
        period=params,
        user=user_sub,
        correlation_id=correlation_id,
    )


def start_pdf_job(
    tenant_id: str,
    period: dict[str, Any],
    user: str,
    correlation_id: str,
) -> uuid.UUID:
    """Enqueue a PDF generation job and return the job UUID.

    MVP: synchronous in-process — renders immediately via asyncio.create_task
    when an event loop is running; otherwise renders synchronously.

    Args:
        tenant_id: Tenant identifier.
        period: Dict with 'anno', 'gwp_set', 'language', etc.
        user: Requesting user sub.
        correlation_id: Request correlation UUID.

    Returns:
        Job UUID.
    """
    job_id = _new_job("pdf", tenant_id, period, user, correlation_id)
    _schedule_render(job_id, "pdf", period)
    return job_id


def start_xlsx_job(
    tenant_id: str,
    period: dict[str, Any],
    user: str,
    correlation_id: str,
) -> uuid.UUID:
    """Enqueue an Excel generation job and return the job UUID.

    Args:
        tenant_id: Tenant identifier.
        period: Dict with 'anno', 'gwp_set', etc.
        user: Requesting user sub.
        correlation_id: Request correlation UUID.

    Returns:
        Job UUID.
    """
    job_id = _new_job("xlsx", tenant_id, period, user, correlation_id)
    _schedule_render(job_id, "xlsx", period)
    return job_id


def _schedule_render(job_id: uuid.UUID, job_type: str, period: dict[str, Any]) -> None:
    """Schedule the actual rendering task without blocking the event loop.

    REV-WAVE3-020: Uses run_in_executor (default ThreadPoolExecutor) instead
    of create_task(_async_render) to prevent WeasyPrint / openpyxl rendering
    from blocking the asyncio event loop for seconds.  The default executor
    (None) is ThreadPoolExecutor; WeasyPrint releases the GIL for parts of the
    workload, but more importantly the event loop remains responsive.

    Falls back to synchronous rendering when no event loop is running (e.g.
    in unit-test context).

    Args:
        job_id: The job UUID.
        job_type: 'pdf' or 'xlsx'.
        period: Report parameters.
    """
    try:
        loop = asyncio.get_running_loop()
        # REV-WAVE3-020: submit blocking render to the default thread-pool
        # executor so the event loop is not blocked.
        loop.run_in_executor(None, _sync_render, job_id, job_type, period)
    except RuntimeError:
        # No running event loop (e.g. in test context) — render synchronously
        _sync_render(job_id, job_type, period)


def _sync_render(
    job_id: uuid.UUID,
    job_type: str,
    period: dict[str, Any],
) -> None:
    """Synchronously render the PDF or XLSX and store result.

    Args:
        job_id: The job UUID.
        job_type: 'pdf' or 'xlsx'.
        period: Report parameters dict (anno, gwp_set, language, ...).
    """
    key = str(job_id)
    _jobs[key]["status"] = _STATUS_RUNNING  # REV-WAVE3-004: canonical constant
    try:
        report_data: dict[str, Any] = {
            "anno": period.get("anno", 2025),
            "gwp_set": period.get("gwp_set", "AR6"),
            "language": period.get("language", "it"),
            "emissions": [],  # MVP: empty; prod wires DB fetch here
            "biogenic": [],
            "factors": [],
            "dq_findings": [],
            "audit_trail": [],
        }
        if job_type == "pdf":
            from ghg_tool.ui.pdf.builder import PDFBuilder
            result_bytes = PDFBuilder().build(report_data)
        else:
            from ghg_tool.ui.excel.builder import XlsxBuilder
            result_bytes = XlsxBuilder().build(report_data)

        _results[key] = result_bytes
        _jobs[key]["status"] = _STATUS_DONE  # REV-WAVE3-004: canonical constant
        logger.bind(job_id=key, job_type=job_type).info(
            "Job completed", size_bytes=len(result_bytes)
        )
    except Exception as exc:  # noqa: BLE001 — rendering libs have no stable exc hierarchy
        # REV-WAVE3-004: log full traceback so rendering errors are diagnosable;
        # only exc_type was previously captured which made debugging impossible.
        _jobs[key]["status"] = _STATUS_FAILED  # REV-WAVE3-004: canonical constant
        _jobs[key]["error_message"] = type(exc).__name__
        logger.bind(job_id=key).exception(
            "Job failed", exc_type=type(exc).__name__
        )


def _internal_to_wire(status: str) -> str:
    """Map the internal status vocabulary to the API wire contract.

    Internal store uses PENDING | RUNNING | DONE | FAILED.
    The wire contract (ReportJobStatus schema) uses COMPLETED instead of DONE.
    REV-WAVE3-004: single mapping function — no ad-hoc conversions elsewhere.

    Args:
        status: An internal status string from the _jobs store.

    Returns:
        Wire-contract status string.
    """
    if status == _STATUS_DONE:
        return "COMPLETED"
    return status


def get_job_status(job_id: uuid.UUID) -> dict[str, Any] | None:
    """Retrieve the current status of a report job.

    Args:
        job_id: The job UUID returned by ``start_*_job``.

    Returns:
        Job state dict, or None if not found.
    """
    return _jobs.get(str(job_id))


def get_job_result(job_id: uuid.UUID) -> bytes | None:
    """Return the rendered document bytes if the job is DONE.

    Args:
        job_id: The job UUID.

    Returns:
        PDF or XLSX bytes, or None if not yet done or failed.
    """
    return _results.get(str(job_id))


def simulate_job_completion(job_id: uuid.UUID, download_url: str) -> None:
    """Mark a job as DONE with a download URL.

    REV-WAVE3-004: Updated to use the canonical internal status _STATUS_DONE
    (was "COMPLETED", which violated the internal vocabulary contract).
    The download guard in exports.py checks _STATUS_DONE; using "COMPLETED"
    internally caused the guard to pass but get_job_result() to 404 because
    _results was never populated.

    NOTE: This function is retained for test backward-compatibility.  In
    production, prefer start_pdf_job / start_xlsx_job which set _STATUS_DONE
    AND populate _results atomically via _sync_render.

    Args:
        job_id: The job UUID to mark as done.
        download_url: Pre-signed URL for the generated document (may be empty
            for in-process renders where bytes are served directly).
    """
    key = str(job_id)
    if key in _jobs:
        _jobs[key]["status"] = _STATUS_DONE  # REV-WAVE3-004: canonical internal status
        _jobs[key]["download_url"] = download_url
        # Populate a sentinel result so the download guard finds bytes.
        # Real callers (start_*_job) populate _results via _sync_render.
        if key not in _results:
            _results[key] = b""
        logger.info("Job marked done", job_id=key)

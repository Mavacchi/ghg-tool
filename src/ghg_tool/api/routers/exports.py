"""Exports router — PDF and Excel generation job management (FR-27, FR-28).

REV-WAVE3-007: New Celery-backed endpoints (202 + async poll pattern).

Celery endpoints (v1.1+):
  POST /api/v1/exports/pdf           → 202 + {"task_id": "...", "status_url": "..."}
  POST /api/v1/exports/xlsx          → 202 + {"task_id": "...", "status_url": "..."}
  GET  /api/v1/exports/{task_id}/status   → {"state": "...", "result": {...}}
  GET  /api/v1/exports/{task_id}/download → binary (200) when SUCCESS

Legacy sync-backing endpoints (kept for one release cycle — deprecated 2026-08-15):
  GET  /api/v1/exports/jobs/{job_id}          → ReportJobStatus (in-memory store)
  GET  /api/v1/exports/jobs/{job_id}/download → binary stream

Idempotency:
  Callers may supply an ``Idempotency-Key`` header on POST requests.  When
  present the Celery task_id is derived as a deterministic UUID-v5 (namespace
  DNS, value = "<tenant_id>:<idempotency_key>") so that duplicate submissions
  reuse the same task and result rather than spawning a second render.
"""

from __future__ import annotations

import base64
import os
import uuid
import warnings
from typing import Literal, cast

import structlog
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission
from ghg_tool.api.schemas.report_schemas import (
    CeleryJobAccepted,
    CeleryJobStatus,
    ExcelReportRequest,
    PdfReportRequest,
    ReportJobStatus,
)
from ghg_tool.application.services.export_service import (
    _STATUS_DONE,
    _internal_to_wire,
    get_job_result,
    get_job_status,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/exports", tags=["exports"])

_DEPRECATION_SUNSET = "2026-08-15"
_DEPRECATION_HEADER = f'version="1"; sunset="{_DEPRECATION_SUNSET}"'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CELERY_TASK_ALWAYS_EAGER: bool = (
    os.getenv("CELERY_TASK_ALWAYS_EAGER", "false").lower() in ("1", "true", "yes")
)


def _derive_task_id(tenant_id: str, idempotency_key: str | None) -> str | None:
    """Derive a deterministic Celery task_id from an idempotency key.

    Returns a UUID-v5 string when an idempotency key is supplied, otherwise
    None (Celery will generate a random UUID for the task).

    The UUID-v5 namespace is ``uuid.NAMESPACE_DNS``; the name is the
    concatenation ``"<tenant_id>:<idempotency_key>"``.

    Args:
        tenant_id: Tenant UUID string.
        idempotency_key: Optional caller-supplied key.

    Returns:
        Deterministic task_id string, or None.
    """
    if not idempotency_key:
        return None
    name = f"{tenant_id}:{idempotency_key}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


def _status_url(request: Request, task_id: str) -> str:
    """Build the absolute status poll URL for a task.

    Args:
        request: The incoming FastAPI request (used to derive base URL).
        task_id: The Celery task UUID string.

    Returns:
        Absolute URL string.
    """
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/exports/{task_id}/status"


# ---------------------------------------------------------------------------
# Celery-backed endpoints (REV-WAVE3-007) — primary surface
# ---------------------------------------------------------------------------


@router.post(
    "/pdf",
    response_model=CeleryJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue PDF report generation via Celery (admin+)",
    description=(
        "Enqueues a Celery background task for PDF generation (WeasyPrint). "
        "Returns task_id and a status_url for polling. "
        "Supply 'Idempotency-Key' header to deduplicate concurrent submissions. "
        "admin role required (FR-28). REV-WAVE3-007."
    ),
    responses={
        202: {"description": "Task accepted"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role — admin required"},
        422: {"description": "Validation error"},
    },
)
async def trigger_pdf(
    body: PdfReportRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission("reports", "pdf")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CeleryJobAccepted:
    """Enqueue a PDF report generation Celery task.

    Args:
        body: PdfReportRequest with anno, gwp_set, language, stream.
        request: FastAPI Request (used to build status_url).
        user: Authenticated admin user.
        idempotency_key: Optional caller-supplied deduplication key.

    Returns:
        CeleryJobAccepted with task_id and status_url.
    """
    from ghg_tool.application.tasks.export_tasks import export_pdf_task  # deferred import

    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    log.info("trigger_pdf_celery", anno=body.anno, gwp_set=body.gwp_set)

    task_id = _derive_task_id(user.tenant_id, idempotency_key)
    params = body.model_dump()
    params["tenant_id"] = user.tenant_id
    params["correlation_id"] = correlation_id

    task = export_pdf_task.apply_async(
        args=[user.tenant_id, params],
        task_id=task_id,
    )
    return CeleryJobAccepted(
        task_id=task.id,
        status_url=_status_url(request, task.id),
    )


@router.post(
    "/xlsx",
    response_model=CeleryJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue Excel report generation via Celery (admin or editor)",
    description=(
        "Enqueues a Celery background task for Excel generation (openpyxl). "
        "Returns task_id and a status_url for polling. "
        "Supply 'Idempotency-Key' header to deduplicate concurrent submissions. "
        "admin or editor role required (FR-27). REV-WAVE3-007."
    ),
    responses={
        202: {"description": "Task accepted"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role"},
        422: {"description": "Validation error"},
    },
)
async def trigger_xlsx(
    body: ExcelReportRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission("reports", "excel")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CeleryJobAccepted:
    """Enqueue an Excel report generation Celery task.

    Args:
        body: ExcelReportRequest with anno, gwp_set, include flags.
        request: FastAPI Request (used to build status_url).
        user: Authenticated user with reports:excel permission.
        idempotency_key: Optional caller-supplied deduplication key.

    Returns:
        CeleryJobAccepted with task_id and status_url.
    """
    from ghg_tool.application.tasks.export_tasks import export_excel_task  # deferred import

    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    log.info("trigger_xlsx_celery", anno=body.anno, gwp_set=body.gwp_set)

    task_id = _derive_task_id(user.tenant_id, idempotency_key)
    params = body.model_dump()
    params["tenant_id"] = user.tenant_id
    params["correlation_id"] = correlation_id

    task = export_excel_task.apply_async(
        args=[user.tenant_id, params],
        task_id=task_id,
    )
    return CeleryJobAccepted(
        task_id=task.id,
        status_url=_status_url(request, task.id),
    )


@router.get(
    "/{task_id}/status",
    response_model=CeleryJobStatus,
    status_code=status.HTTP_200_OK,
    summary="Poll Celery task status for PDF or Excel generation",
    description=(
        "Returns the current Celery task state. "
        "state = PENDING | STARTED | SUCCESS | FAILURE | REVOKED. "
        "All authenticated roles may poll. REV-WAVE3-007."
    ),
    responses={
        200: {"description": "Task status"},
        401: {"description": "Not authenticated"},
    },
)
async def get_celery_task_status(
    task_id: str,
    user: CurrentUser = Depends(require_permission("reports", "status")),
) -> CeleryJobStatus:
    """Return the current status of a Celery export task.

    Args:
        task_id: The UUID string returned by POST /pdf or POST /xlsx.
        user: Any authenticated user.

    Returns:
        CeleryJobStatus with state, and result/error when terminal.
    """
    from ghg_tool.infrastructure.celery_app import celery_app

    ar = AsyncResult(task_id, app=celery_app)
    state: str = ar.state  # PENDING | STARTED | SUCCESS | FAILURE | REVOKED | RETRY

    # Normalise state to our API vocabulary
    allowed_states = {"PENDING", "STARTED", "SUCCESS", "FAILURE", "REVOKED", "RETRY"}
    if state not in allowed_states:
        state = "PENDING"

    result_payload: dict[str, object] | None = None
    error_detail: str | None = None

    if state == "SUCCESS":
        raw = ar.result
        if isinstance(raw, dict):
            # Strip the bulky base64 payload from the status response —
            # callers use GET /download for the actual bytes.
            result_payload = {k: v for k, v in raw.items() if k != "result_b64"}
    elif state == "FAILURE":
        exc = ar.result  # stores the exception instance on failure
        error_detail = str(exc) if exc is not None else "Unknown error"

    return CeleryJobStatus(
        task_id=task_id,
        state=cast(
            Literal["PENDING", "STARTED", "SUCCESS", "FAILURE", "REVOKED", "RETRY"],
            state,
        ),
        result=result_payload,
        error=error_detail,
    )


@router.get(
    "/{task_id}/download",
    status_code=status.HTTP_200_OK,
    summary="Download completed PDF or Excel from Celery task result",
    description=(
        "Streams the generated document bytes for a completed Celery task. "
        "Returns 409 if task is not yet SUCCESS, 500 if task FAILED. "
        "REV-WAVE3-007."
    ),
    responses={
        200: {"description": "Binary file stream"},
        401: {"description": "Not authenticated"},
        409: {"description": "Task not yet completed"},
        500: {"description": "Task failed — detail in body"},
    },
)
async def download_celery_export(
    task_id: str,
    user: CurrentUser = Depends(require_permission("reports", "status")),
) -> Response:
    """Stream the generated document for a completed Celery task.

    Tenant isolation: the task result embeds ``tenant_id``; we verify it
    matches the caller's tenant before returning bytes.  A mismatch surfaces
    as 404 (same as "not found") to avoid existence disclosure.

    Args:
        task_id: The Celery task UUID string.
        user: Any authenticated user.

    Returns:
        Binary Response with appropriate content-type and Content-Disposition.

    Raises:
        HTTPException 404: task_id not found or belongs to another tenant.
        HTTPException 409: task is not yet in SUCCESS state.
        HTTPException 500: task is in FAILURE state.
    """
    from ghg_tool.infrastructure.celery_app import celery_app

    correlation_id = get_correlation_id()
    ar = AsyncResult(task_id, app=celery_app)
    state: str = ar.state

    if state == "FAILURE":
        exc = ar.result
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "type": "about:blank",
                "title": "Task Failed",
                "status": 500,
                "detail": str(exc) if exc is not None else "Export task failed",
                "correlation_id": correlation_id,
            },
        )

    if state != "SUCCESS":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "about:blank",
                "title": "Conflict",
                "status": 409,
                "detail": f"Export task {task_id} is not yet complete (state={state})",
                "correlation_id": correlation_id,
            },
        )

    raw: dict[str, object] = ar.result
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"detail": "Unexpected task result format"},
        )

    # Tenant isolation check — collapse mismatch to 404
    result_tenant = str(raw.get("tenant_id", ""))
    if result_tenant != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "about:blank",
                "title": "Not Found",
                "status": 404,
                "detail": f"Export task {task_id} not found",
                "correlation_id": correlation_id,
            },
        )

    result_b64 = str(raw.get("result_b64", ""))
    try:
        result_bytes = base64.b64decode(result_b64)
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"detail": "Could not decode task result bytes"},
        ) from None

    job_type = str(raw.get("job_type", "pdf"))
    if job_type == "pdf":
        media_type = "application/pdf"
        filename = f"ghg_report_{task_id}.pdf"
    else:
        media_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"ghg_report_{task_id}.xlsx"

    return Response(
        content=result_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Legacy in-memory endpoints — deprecated 2026-08-15 (REV-WAVE3-007)
# These endpoints are kept for one release cycle to avoid breaking existing
# integrations.  The Deprecation header signals the sunset date to API clients.
# ---------------------------------------------------------------------------


@router.get(
    "/jobs/{job_id}",
    response_model=ReportJobStatus,
    status_code=status.HTTP_200_OK,
    summary="[DEPRECATED] Poll job status — in-memory store (sunset 2026-08-15)",
    description=(
        "DEPRECATED: Use GET /api/v1/exports/{task_id}/status instead. "
        "This endpoint uses the in-memory job store and does not work across "
        "multiple API replicas. Sunset: 2026-08-15."
    ),
    responses={
        200: {"description": "Job status"},
        401: {"description": "Not authenticated"},
        404: {"description": "Job not found"},
    },
    deprecated=True,
)
async def get_export_job_status(
    job_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission("reports", "status")),
) -> ReportJobStatus:
    """Return the current status of a legacy in-process export job.

    Args:
        job_id: The UUID returned by POST /pdf or POST /xlsx (legacy).
        user: Any authenticated user.

    Returns:
        ReportJobStatus with current status and download_url if DONE.

    Raises:
        HTTPException: 404 if job_id not found.
    """
    warnings.warn(
        "GET /api/v1/exports/jobs/{job_id} is deprecated (sunset 2026-08-15). "
        "Use GET /api/v1/exports/{task_id}/status instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    correlation_id = get_correlation_id()
    job = get_job_status(job_id)
    if job is None or job.get("tenant_id") != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "about:blank",
                "title": "Not Found",
                "status": 404,
                "detail": f"Export job {job_id} not found",
                "correlation_id": correlation_id,
            },
        )
    _raw = _internal_to_wire(job["status"])
    api_status = cast(Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"], _raw)
    response = ReportJobStatus(
        job_id=uuid.UUID(job["job_id"]),
        status=api_status,
        download_url=job.get("download_url"),
        error_message=job.get("error_message"),
        correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
    )
    return response


@router.get(
    "/jobs/{job_id}/download",
    status_code=status.HTTP_200_OK,
    summary="[DEPRECATED] Download legacy in-process export (sunset 2026-08-15)",
    description=(
        "DEPRECATED: Use GET /api/v1/exports/{task_id}/download instead. "
        "Sunset: 2026-08-15."
    ),
    responses={
        200: {"description": "Binary file stream"},
        401: {"description": "Not authenticated"},
        404: {"description": "Job not found"},
        409: {"description": "Job not yet completed"},
    },
    deprecated=True,
)
async def download_export(
    job_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission("reports", "status")),
) -> Response:
    """Stream the generated document for a completed legacy job.

    Args:
        job_id: The job UUID from the legacy in-memory store.
        user: Any authenticated user.

    Returns:
        Binary Response with appropriate content-type header.

    Raises:
        HTTPException: 404 if job not found; 409 if not DONE.
    """
    warnings.warn(
        "GET /api/v1/exports/jobs/{job_id}/download is deprecated (sunset 2026-08-15). "
        "Use GET /api/v1/exports/{task_id}/download instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    correlation_id = get_correlation_id()
    job = get_job_status(job_id)
    if job is None or job.get("tenant_id") != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "about:blank",
                "title": "Not Found",
                "status": 404,
                "detail": f"Export job {job_id} not found",
                "correlation_id": correlation_id,
            },
        )
    if job["status"] != _STATUS_DONE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "about:blank",
                "title": "Conflict",
                "status": 409,
                "detail": f"Export job {job_id} is not yet complete (status={job['status']})",
                "correlation_id": correlation_id,
            },
        )

    result = get_job_result(job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "about:blank",
                "title": "Not Found",
                "status": 404,
                "detail": f"Result bytes for job {job_id} not available",
                "correlation_id": correlation_id,
            },
        )

    job_type = job.get("type", "pdf")
    if job_type == "pdf":
        media_type = "application/pdf"
        filename = f"ghg_report_{job_id}.pdf"
    else:
        media_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"ghg_report_{job_id}.xlsx"

    return Response(
        content=result,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

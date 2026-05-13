"""Exports router — PDF and Excel generation job management (FR-27, FR-28).

Endpoints:
  POST /api/v1/exports/pdf     → start PDF job (esg_manager+)
  POST /api/v1/exports/xlsx    → start XLSX job (esg_manager or data_steward)
  GET  /api/v1/exports/jobs/{job_id}          → job status
  GET  /api/v1/exports/jobs/{job_id}/download → binary stream (PDF/XLSX)
"""

from __future__ import annotations

import uuid
from typing import Literal, cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission
from ghg_tool.api.schemas.report_schemas import (
    ExcelReportRequest,
    PdfReportRequest,
    ReportJobStatus,
)
from ghg_tool.application.services.export_service import (
    get_job_result,
    get_job_status,
    start_pdf_job,
    start_xlsx_job,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/exports", tags=["exports"])


@router.post(
    "/pdf",
    response_model=ReportJobStatus,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger CSRD ESRS E1-6 PDF report generation (esg_manager+)",
    description=(
        "Enqueues a PDF generation job (WeasyPrint). Returns a job_id for polling. "
        "esg_manager role required (FR-28). "
        "MVP: synchronous in-process; replace with Celery in production."
    ),
    responses={
        202: {"description": "Job accepted"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role — esg_manager required"},
        422: {"description": "Validation error"},
    },
)
async def trigger_pdf(
    body: PdfReportRequest,
    user: CurrentUser = Depends(require_permission("reports", "pdf")),
) -> ReportJobStatus:
    """Enqueue a PDF report generation job.

    Args:
        body: PdfReportRequest with anno, gwp_set, language, stream.
        user: Authenticated esg_manager user.

    Returns:
        ReportJobStatus with status='PENDING' and the new job_id.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    log.info("trigger_pdf_export", anno=body.anno, gwp_set=body.gwp_set)

    job_id = start_pdf_job(
        tenant_id=user.tenant_id,
        period=body.model_dump(),
        user=user.sub,
        correlation_id=correlation_id,
    )
    return ReportJobStatus(
        job_id=job_id,
        status="PENDING",
        correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
    )


@router.post(
    "/xlsx",
    response_model=ReportJobStatus,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger multi-sheet Excel export (esg_manager or data_steward)",
    description=(
        "Enqueues an Excel generation job (openpyxl, 11 sheets). Returns job_id. "
        "esg_manager or data_steward role required (FR-27). "
        "MVP: synchronous in-process; replace with Celery in production."
    ),
    responses={
        202: {"description": "Job accepted"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role"},
        422: {"description": "Validation error"},
    },
)
async def trigger_xlsx(
    body: ExcelReportRequest,
    user: CurrentUser = Depends(require_permission("reports", "excel")),
) -> ReportJobStatus:
    """Enqueue an Excel report generation job.

    Args:
        body: ExcelReportRequest with anno, gwp_set, include flags.
        user: Authenticated user with reports:excel permission.

    Returns:
        ReportJobStatus with status='PENDING' and the new job_id.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    log.info("trigger_xlsx_export", anno=body.anno, gwp_set=body.gwp_set)

    job_id = start_xlsx_job(
        tenant_id=user.tenant_id,
        period=body.model_dump(),
        user=user.sub,
        correlation_id=correlation_id,
    )
    return ReportJobStatus(
        job_id=job_id,
        status="PENDING",
        correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
    )


@router.get(
    "/jobs/{job_id}",
    response_model=ReportJobStatus,
    status_code=status.HTTP_200_OK,
    summary="Poll job status for PDF or Excel generation",
    description=(
        "Returns the current status of a PDF or Excel generation job. "
        "All authenticated roles may poll."
    ),
    responses={
        200: {"description": "Job status"},
        401: {"description": "Not authenticated"},
        404: {"description": "Job not found"},
    },
)
async def get_export_job_status(
    job_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission("reports", "status")),
) -> ReportJobStatus:
    """Return the current status of an export job.

    Args:
        job_id: The UUID returned by POST /pdf or POST /xlsx.
        user: Any authenticated user.

    Returns:
        ReportJobStatus with current status and download_url if DONE.

    Raises:
        HTTPException: 404 if job_id not found.
    """
    correlation_id = get_correlation_id()
    job = get_job_status(job_id)
    if job is None:
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
    # Map internal status DONE → COMPLETED for API consumers
    _raw = "COMPLETED" if job["status"] == "DONE" else job["status"]
    api_status = cast(Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"], _raw)
    return ReportJobStatus(
        job_id=uuid.UUID(job["job_id"]),
        status=api_status,
        download_url=job.get("download_url"),
        error_message=job.get("error_message"),
        correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
    )


@router.get(
    "/jobs/{job_id}/download",
    status_code=status.HTTP_200_OK,
    summary="Download generated PDF or Excel binary",
    description=(
        "Returns the raw PDF or XLSX bytes for a completed export job. "
        "Returns 404 if job not found, 409 if not yet completed."
    ),
    responses={
        200: {"description": "Binary file stream"},
        401: {"description": "Not authenticated"},
        404: {"description": "Job not found"},
        409: {"description": "Job not yet completed"},
    },
)
async def download_export(
    job_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission("reports", "status")),
) -> Response:
    """Stream the generated document for a completed job.

    Args:
        job_id: The job UUID.
        user: Any authenticated user.

    Returns:
        Binary Response with appropriate content-type header.

    Raises:
        HTTPException: 404 if job not found; 409 if not DONE.
    """
    correlation_id = get_correlation_id()
    job = get_job_status(job_id)
    if job is None:
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
    if job["status"] not in ("DONE", "COMPLETED"):
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

"""Reports router — /api/v1/reports (FR-27, FR-28).

DEPRECATED — REV-WAVE3-002.
This router is a wave-2 stub: it calls create_report_job() which queues a
job record but does NOT invoke PDFBuilder or XlsxBuilder.  The functional
rendering pipeline lives in the exports router (/api/v1/exports/*).

New clients MUST use:
  POST /api/v1/exports/pdf    (instead of /api/v1/reports/pdf)
  POST /api/v1/exports/xlsx   (instead of /api/v1/reports/excel)
  GET  /api/v1/exports/jobs/{job_id} (instead of /api/v1/reports/status/{id})

This router is kept to avoid breaking existing integrations during the
transition period.  It will be removed in the next major API version.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission
from ghg_tool.api.schemas.report_schemas import (
    ExcelReportRequest,
    PdfReportRequest,
    ReportJobStatus,
)
from ghg_tool.application.services.export_service import (
    create_report_job,
    get_job_status,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.post(
    "/pdf",
    response_model=ReportJobStatus,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger CSRD ESRS E1-6 PDF report generation (esg_manager only)",
    description=(
        "Enqueues an async PDF generation job. Returns a job_id for polling. "
        "Actual PDF rendering (WeasyPrint) is implemented in wave 3. "
        "esg_manager role only (FR-28)."
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
        body: ``PdfReportRequest`` with anno, gwp_set, language, stream.
        user: Authenticated esg_manager user.

    Returns:
        ``ReportJobStatus`` with ``status='PENDING'`` and the new ``job_id``.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    log.info("trigger_pdf", anno=body.anno, gwp_set=body.gwp_set)

    job_id = create_report_job(
        job_type="pdf",
        params=body.model_dump(),
        user_sub=user.sub,
        correlation_id=correlation_id,
    )
    return ReportJobStatus(
        job_id=job_id,
        status="PENDING",
        correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
    )


@router.post(
    "/excel",
    response_model=ReportJobStatus,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger multi-sheet Excel export (data_steward or esg_manager)",
    description=(
        "Enqueues an async Excel generation job. Returns a job_id for polling. "
        "Actual openpyxl rendering is implemented in wave 3. "
        "data_steward or esg_manager role required (FR-27)."
    ),
    responses={
        202: {"description": "Job accepted"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role"},
        422: {"description": "Validation error"},
    },
)
async def trigger_excel(
    body: ExcelReportRequest,
    user: CurrentUser = Depends(require_permission("reports", "excel")),
) -> ReportJobStatus:
    """Enqueue an Excel report generation job.

    Args:
        body: ``ExcelReportRequest`` with anno, gwp_set, include flags.
        user: Authenticated user with reports:excel permission.

    Returns:
        ``ReportJobStatus`` with ``status='PENDING'`` and the new ``job_id``.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    log.info("trigger_excel", anno=body.anno, gwp_set=body.gwp_set)

    job_id = create_report_job(
        job_type="excel",
        params=body.model_dump(),
        user_sub=user.sub,
        correlation_id=correlation_id,
    )
    return ReportJobStatus(
        job_id=job_id,
        status="PENDING",
        correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
    )


@router.get(
    "/status/{job_id}",
    response_model=ReportJobStatus,
    status_code=status.HTTP_200_OK,
    summary="Poll the status of a report generation job",
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
async def get_report_status(
    job_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission("reports", "status")),
) -> ReportJobStatus:
    """Return the current status of a report job.

    Args:
        job_id: The UUID returned by the POST /pdf or POST /excel endpoint.
        user: Any authenticated user.

    Returns:
        ``ReportJobStatus`` with current status, download_url if completed.

    Raises:
        HTTPException: 404 if the job_id is not found.
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
                "detail": f"Report job {job_id} not found",
                "correlation_id": correlation_id,
            },
        )
    return ReportJobStatus(
        job_id=uuid.UUID(job["job_id"]),
        status=job["status"],
        download_url=job.get("download_url"),
        error_message=job.get("error_message"),
        correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
    )

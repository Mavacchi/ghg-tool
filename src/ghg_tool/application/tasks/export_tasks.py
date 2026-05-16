"""Celery tasks for PDF and Excel export generation — REV-WAVE3-007.

Each task wraps the synchronous rendering functions already present in
``ghg_tool.ui.pdf.builder`` and ``ghg_tool.ui.excel.builder``.

Task names are stable identifiers; do not rename without a migration plan.

Public tasks:
    export_pdf_task   — ``ghg_tool.export_pdf``
    export_excel_task — ``ghg_tool.export_excel``

Return value schema (JSON-serialisable dict):
    {
        "job_id":     str,        # UUID passed in as ``job_id``
        "job_type":   "pdf"|"excel",
        "size_bytes": int,
        "result_b64": str,        # base64-encoded document bytes
        "tenant_id":  str,
    }

Error handling:
    Unhandled exceptions propagate to Celery and are stored as FAILURE state
    in the result backend.  The router reads ``AsyncResult.info`` to surface the
    error message.

Idempotency:
    The caller (exports router) may pass an ``idempotency_key`` in ``params``.
    When present, the task ID is derived as a deterministic UUID v5 from the
    key so that two identical submissions share the same Celery task and result.
    See ``exports.py`` for key derivation.

Worker log pattern (structured JSON via structlog):
    Every task emits ``task_started``, ``task_completed``, and ``task_failed``
    events with ``job_id``, ``job_type``, ``tenant_id``, and ``size_bytes`` (on
    success).  These fields enable Grafana / Loki queries without parsing free
    text.
"""

from __future__ import annotations

import base64
from typing import Any

import structlog

from ghg_tool.infrastructure.celery_app import celery_app

logger = structlog.get_logger(__name__)


def _build_report_data(params: dict[str, Any]) -> dict[str, Any]:
    """Assemble the report_data dict expected by PDF/Excel builders.

    In production the ``emissions``, ``biogenic``, ``factors`` etc. fields
    should be populated from a DB fetch keyed on ``params['tenant_id']`` and
    ``params['anno']``.  The current implementation preserves the MVP behaviour
    of empty lists; a follow-up task (DB wire-up) populates them.

    Args:
        params: Raw parameters dict from the API request (anno, gwp_set, …).

    Returns:
        dict suitable for passing to PDFBuilder.build() or XlsxBuilder.build().
    """
    return {
        "anno": params.get("anno", 2025),
        "gwp_set": params.get("gwp_set", "AR6"),
        "language": params.get("language", "it"),
        "emissions": [],
        "biogenic": [],
        "factors": [],
        "dq_findings": [],
        "audit_trail": [],
    }


@celery_app.task(  # type: ignore[misc]
    bind=True,
    name="ghg_tool.export_pdf",
    # No automatic retry — PDF render is deterministic; a retry would produce
    # the same failure.  Callers should inspect FAILURE state and notify user.
    max_retries=0,
    acks_late=True,  # ack only after success so a worker crash re-queues the task
)
def export_pdf_task(  # noqa: ANN401
    self: Any,
    tenant_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Generate a PDF report in a Celery worker process.

    Args:
        self: Celery bound-task instance (provides self.request.id).
        tenant_id: Tenant identifier — passed through to result metadata.
        params: Report parameters (anno, gwp_set, language, …).

    Returns:
        Result dict with ``job_id``, ``job_type``, ``size_bytes``, ``result_b64``,
        and ``tenant_id``.

    Raises:
        Exception: Any exception raised by PDFBuilder propagates as FAILURE.
    """
    job_id: str = str(self.request.id)
    log = logger.bind(job_id=job_id, job_type="pdf", tenant_id=tenant_id[:8])
    log.info("task_started")

    from ghg_tool.ui.pdf.builder import PDFBuilder  # local import — avoid circular at module load

    report_data = _build_report_data(params)
    try:
        result_bytes: bytes = PDFBuilder().build(report_data)
    except Exception:
        log.exception("task_failed")
        raise

    encoded = base64.b64encode(result_bytes).decode("ascii")
    size = len(result_bytes)
    log.info("task_completed", size_bytes=size)
    return {
        "job_id": job_id,
        "job_type": "pdf",
        "size_bytes": size,
        "result_b64": encoded,
        "tenant_id": tenant_id,
    }


@celery_app.task(  # type: ignore[misc]
    bind=True,
    name="ghg_tool.export_excel",
    max_retries=0,
    acks_late=True,
)
def export_excel_task(self: Any, tenant_id: str, params: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN401
    """Generate an Excel report in a Celery worker process.

    Args:
        self: Celery bound-task instance.
        tenant_id: Tenant identifier.
        params: Report parameters (anno, gwp_set, include_audit_trail, …).

    Returns:
        Result dict with ``job_id``, ``job_type``, ``size_bytes``, ``result_b64``,
        and ``tenant_id``.

    Raises:
        Exception: Any exception raised by XlsxBuilder propagates as FAILURE.
    """
    job_id: str = str(self.request.id)
    log = logger.bind(job_id=job_id, job_type="excel", tenant_id=tenant_id[:8])
    log.info("task_started")

    from ghg_tool.ui.excel.builder import XlsxBuilder  # local import

    report_data = _build_report_data(params)
    try:
        result_bytes = XlsxBuilder().build(report_data)
    except Exception:
        log.exception("task_failed")
        raise

    encoded = base64.b64encode(result_bytes).decode("ascii")
    size = len(result_bytes)
    log.info("task_completed", size_bytes=size)
    return {
        "job_id": job_id,
        "job_type": "excel",
        "size_bytes": size,
        "result_b64": encoded,
        "tenant_id": tenant_id,
    }

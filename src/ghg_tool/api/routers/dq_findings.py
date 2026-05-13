"""DQ findings router — /api/v1/dq-findings (FR-32).

All authenticated roles can read DQ findings.
Only esg_manager can create waiver resolutions (append-only new row pattern).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission
from ghg_tool.api.schemas.common import CursorPage
from ghg_tool.api.schemas.dq_schemas import DqFindingFilter, DqFindingResponse, WaiverRequest
from ghg_tool.infrastructure.db.models.dq_finding import DqFinding
from ghg_tool.infrastructure.db.repositories.dq_findings_repository import (
    DQFindingsRepository,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/dq-findings", tags=["dq-findings"])


@router.get(
    "/",
    response_model=CursorPage[DqFindingResponse],
    status_code=status.HTTP_200_OK,
    summary="List data quality findings (filterable, cursor-paginated)",
    description=(
        "Returns DQ findings from calc.dq_findings. Filterable by severity, rule_id, "
        "resolution_status, anno, codice_sito, correlation_id. All roles may read."
    ),
    responses={
        200: {"description": "DQ findings"},
        401: {"description": "Not authenticated"},
    },
)
async def list_findings(
    filters: Annotated[DqFindingFilter, Depends()],
    user: CurrentUser = Depends(require_permission("dq_findings", "read")),
    session: AsyncSession = Depends(get_db),
) -> CursorPage[DqFindingResponse]:
    """Return a filtered, paginated list of DQ findings.

    Args:
        filters: Query parameter filter values.
        user: Authenticated user with dq_findings:read permission.
        session: Authenticated DB session.

    Returns:
        Paginated DQ findings.
    """
    correlation_id = get_correlation_id()
    logger.bind(correlation_id=correlation_id).info("list_findings")

    repo = DQFindingsRepository(session)
    rows = await repo.get_open_findings(
        tenant_id=uuid.UUID(user.tenant_id),
        severity=filters.severity,
    )

    # Additional in-Python filters for fields not in get_open_findings
    if filters.resolution_status is not None and filters.resolution_status != "OPEN":
        rows = []  # get_open_findings only returns OPEN; handle via raw query in wave 3
    if filters.rule_id is not None:
        rows = [r for r in rows if r.rule_id == filters.rule_id]
    if filters.anno is not None:
        rows = [r for r in rows if r.anno == filters.anno]
    if filters.codice_sito is not None:
        rows = [r for r in rows if r.codice_sito == filters.codice_sito]
    if filters.correlation_id is not None:
        rows = [r for r in rows if r.correlation_id == filters.correlation_id]

    items = [DqFindingResponse.model_validate(r) for r in rows[: filters.limit]]
    next_cursor: str | None = None
    if len(rows) > filters.limit:
        from ghg_tool.api.dependencies.pagination import encode_cursor
        next_cursor = encode_cursor(rows[filters.limit - 1].id)

    return CursorPage(items=items, next_cursor=next_cursor, total=len(rows))


@router.post(
    "/waiver/{finding_id}",
    response_model=DqFindingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Apply a waiver to a DQ finding (esg_manager only, append-only)",
    description=(
        "Creates a new resolution row with resolution_status='WAIVED' and "
        "parent_finding_id pointing to the original finding. Does not UPDATE "
        "the original row (append-only pattern). esg_manager role only."
    ),
    responses={
        201: {"description": "Waiver applied"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role — esg_manager required"},
        404: {"description": "Finding not found"},
        422: {"description": "Validation error"},
    },
)
async def waive_finding(
    finding_id: uuid.UUID,
    body: WaiverRequest,
    user: CurrentUser = Depends(require_permission("dq_findings", "waiver")),
    session: AsyncSession = Depends(get_db),
) -> DqFindingResponse:
    """Apply a waiver resolution to an open DQ finding.

    Creates a new DQ finding row with ``resolution_status='WAIVED'`` and
    ``parent_finding_id`` set to the original finding UUID.  The original
    row is never updated (append-only).

    Args:
        finding_id: UUID of the DQ finding to waive.
        body: ``WaiverRequest`` with reason_code and justification.
        user: Authenticated esg_manager user.
        session: Authenticated DB session.

    Returns:
        The newly created waiver resolution row.

    Raises:
        HTTPException: 404 if finding not found; 403 if not esg_manager.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    log.info("waive_finding", finding_id=str(finding_id), reason_code=body.reason_code)

    from sqlalchemy import select
    result = await session.execute(
        select(DqFinding).where(DqFinding.id == finding_id)
    )
    original = result.scalar_one_or_none()
    if original is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "about:blank",
                "title": "Not Found",
                "status": 404,
                "detail": f"DQ finding {finding_id} not found",
                "correlation_id": correlation_id,
            },
        )

    now = datetime.now(tz=timezone.utc)
    waiver_row = DqFinding(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(user.tenant_id),
        correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
        parent_finding_id=finding_id,
        rule_id=original.rule_id,
        severity=original.severity,
        scope=original.scope,
        codice_sito=original.codice_sito,
        anno=original.anno,
        metric=original.metric,
        dq_report_version=original.dq_report_version,
        blocks_pipeline=False,
        resolution_status="WAIVED",
        waiver_reason_code=body.reason_code,
        waiver_justification=body.justification,
        waiver_approved_by=user.sub,
        resolved_at=now,
    )

    repo = DQFindingsRepository(session)
    persisted = await repo.insert_finding(waiver_row)
    log.info("Waiver applied", waiver_id=str(persisted.id))
    return DqFindingResponse.model_validate(persisted)

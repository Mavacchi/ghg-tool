"""SBTi targets router -- ESRS E1-4 science-based reduction targets.

Endpoints:
  GET  /api/v1/sbti/targets                       List targets (all roles).
  POST /api/v1/sbti/targets                       Create target (admin).
  PATCH /api/v1/sbti/targets/{uuid}/deactivate    Deactivate (admin).
  GET  /api/v1/sbti/targets/{uuid}/trajectory     Trajectory + actuals (all roles).

Immutability invariant: only ``is_active`` True->False is permitted on existing
rows; the DB trigger ``trg_sbti_target_immutability`` enforces this at the
Postgres layer as a second line of defence.

Tenant isolation: ``tenant_id`` is always derived from the JWT; it is never
read from the request body.  RLS provides a third line of defence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission, require_role
from ghg_tool.api.schemas.sbti_schemas import (
    SbtiTargetCreate,
    SbtiTargetResponse,
    TrajectoryPointResponse,
    TrajectoryResponse,
)
from ghg_tool.application.services.sbti_service import (
    TargetStatus,
    annotate_actuals,
    assess_status,
    compute_trajectory,
)
from ghg_tool.domain.entities.sbti_target import SbtiTarget as SbtiTargetDomain
from ghg_tool.infrastructure.db.models.audit_log import AuditLog
from ghg_tool.infrastructure.db.models.sbti_target import SbtiTarget
from ghg_tool.infrastructure.security import siem

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/sbti", tags=["sbti"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _problem(
    http_status: int,
    title: str,
    detail: str,
    error_code: str,
    correlation_id: str,
) -> HTTPException:
    """Build an RFC 7807 HTTPException.

    Args:
        http_status: HTTP status code.
        title: Short problem title.
        detail: Human-readable explanation.
        error_code: Machine-readable error slug.
        correlation_id: Request trace ID.

    Returns:
        An HTTPException with application/problem+json body.
    """
    return HTTPException(
        status_code=http_status,
        detail={
            "type": "about:blank",
            "title": title,
            "status": http_status,
            "detail": detail,
            "error_code": error_code,
            "correlation_id": correlation_id,
        },
    )


def _orm_to_response(row: SbtiTarget) -> SbtiTargetResponse:
    """Convert an ORM row to the API response schema.

    Args:
        row: SQLAlchemy ORM instance.

    Returns:
        Validated ``SbtiTargetResponse``.
    """
    return SbtiTargetResponse.model_validate(row)


def _orm_to_domain(row: SbtiTarget) -> SbtiTargetDomain:
    """Convert an ORM row to the frozen domain dataclass.

    Args:
        row: SQLAlchemy ORM instance.

    Returns:
        ``SbtiTargetDomain`` frozen dataclass for service calls.
    """
    return SbtiTargetDomain(
        target_id=row.target_id,
        tenant_id=row.tenant_id,
        name=row.name,
        scope_coverage=row.scope_coverage,
        baseline_year=int(row.baseline_year),
        baseline_tco2e=Decimal(str(row.baseline_tco2e)),
        target_year=int(row.target_year),
        target_tco2e=Decimal(str(row.target_tco2e)),
        reduction_pct=Decimal(str(row.reduction_pct)),
        alignment=row.alignment,
        methodology=row.methodology,
        sbti_approval_status=row.sbti_approval_status,
        sbti_validation_date=row.sbti_validation_date,
        created_by=row.created_by,
        created_at=row.created_at,
        is_active=row.is_active,
    )


async def _fetch_target_or_404(
    session: AsyncSession,
    target_id: uuid.UUID,
    tenant_id: uuid.UUID,
    correlation_id: str,
) -> SbtiTarget:
    """Load a target by PK within the caller's tenant or raise 404.

    Args:
        session: Async DB session.
        target_id: Target UUID from the URL path.
        tenant_id: Tenant UUID from the JWT.
        correlation_id: Request trace ID.

    Returns:
        The matching SbtiTarget ORM row.

    Raises:
        HTTPException: 404 if not found or belongs to a different tenant.
    """
    stmt = select(SbtiTarget).where(
        SbtiTarget.target_id == target_id,
        SbtiTarget.tenant_id == tenant_id,
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            "Not Found",
            f"SBTi target {target_id} not found in this tenant.",
            "sbti_target_not_found",
            correlation_id,
        )
    return row


async def _load_actuals(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    scope_coverage: str,
    baseline_year: int,
    target_year: int,
) -> dict[int, Decimal]:
    """Load consolidated emissions aggregated by year for a scope coverage.

    Maps the ``scope_coverage`` key to the sub_scope values used in
    calc.emissions_consolidated.  A best-effort mapping is used; unmapped
    scope keys return an empty dict (trajectory is shown, status is NO_DATA).

    Args:
        session: Async DB session.
        tenant_id: Tenant UUID for filtering.
        scope_coverage: SBTi scope mix key (e.g. 'S1+S2_LB').
        baseline_year: First year of the trajectory.
        target_year: Last year of the trajectory.

    Returns:
        Mapping of year -> total tco2e (Decimal) for matched rows.
    """
    # Map SBTi scope_coverage keys to sub_scope values in emissions_consolidated.
    _scope_map: dict[str, list[str]] = {
        "S1": ["combustion", "process", "fugitive"],
        "S2_LB": ["2_LB"],
        "S2_MB": ["2_MB"],
        "S3": ["3_cat1", "3_cat2", "3_cat3", "3_cat4", "3_cat5", "3_cat6",
               "3_cat7", "3_cat9", "3_cat11", "3_cat12"],
        "S1+S2_LB": ["combustion", "process", "fugitive", "2_LB"],
        "S1+S2_MB": ["combustion", "process", "fugitive", "2_MB"],
        "S1+S2_MB+S3": [
            "combustion", "process", "fugitive", "2_MB",
            "3_cat1", "3_cat2", "3_cat3", "3_cat4", "3_cat5", "3_cat6",
            "3_cat7", "3_cat9", "3_cat11", "3_cat12",
        ],
    }
    sub_scopes = _scope_map.get(scope_coverage)
    if not sub_scopes:
        return {}

    stmt = text(
        """
        SELECT anno, SUM(tco2e) AS total
        FROM calc.emissions_consolidated
        WHERE tenant_id = :tenant_id
          AND sub_scope = ANY(:sub_scopes)
          AND anno BETWEEN :from_year AND :to_year
          AND valid_to IS NULL
        GROUP BY anno
        ORDER BY anno
        """
    )
    result = await session.execute(
        stmt,
        {
            "tenant_id": tenant_id,
            "sub_scopes": sub_scopes,
            "from_year": baseline_year,
            "to_year": target_year,
        },
    )
    return {row.anno: Decimal(str(row.total)) for row in result}


# ---------------------------------------------------------------------------
# GET /api/v1/sbti/targets
# ---------------------------------------------------------------------------


@router.get(
    "/targets",
    response_model=list[SbtiTargetResponse],
    status_code=status.HTTP_200_OK,
    summary="List SBTi targets for the caller's tenant",
    description=(
        "Returns all active SBTi targets for the authenticated tenant. "
        "Query ``?include_inactive=true`` is restricted to admin. "
        "All authenticated roles may read active targets."
    ),
    responses={
        200: {"description": "List of SBTi targets"},
        401: {"description": "Not authenticated"},
        403: {"description": "include_inactive=true requires admin role"},
    },
)
async def list_targets(
    include_inactive: Annotated[bool, Query()] = False,
    user: CurrentUser = Depends(require_permission("sbti_targets", "read")),
    session: AsyncSession = Depends(get_db),
) -> list[SbtiTargetResponse]:
    """List SBTi targets.

    Args:
        include_inactive: When True, include deactivated targets. admin only.
        user: Authenticated user (any role).
        session: Async DB session.

    Returns:
        List of SbtiTargetResponse sorted by target_year descending.

    Raises:
        HTTPException: 403 if non-admin requests include_inactive=true.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub)

    if include_inactive and user.role != "admin":
        raise _problem(
            status.HTTP_403_FORBIDDEN,
            "Forbidden",
            "include_inactive=true requires admin role.",
            "insufficient_role",
            correlation_id,
        )

    stmt = select(SbtiTarget).where(
        SbtiTarget.tenant_id == uuid.UUID(user.tenant_id)
    )
    if not include_inactive:
        stmt = stmt.where(SbtiTarget.is_active.is_(True))
    stmt = stmt.order_by(SbtiTarget.target_year.desc())

    result = await session.execute(stmt)
    rows = result.scalars().all()
    log.info("sbti_list_targets", count=len(rows), include_inactive=include_inactive)
    return [_orm_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# POST /api/v1/sbti/targets
# ---------------------------------------------------------------------------


@router.post(
    "/targets",
    response_model=SbtiTargetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new SBTi target (admin only)",
    description=(
        "Creates a new append-only SBTi reduction target for the caller's tenant. "
        "All domain invariants (year order, tco2e bounds, enum checks) are enforced "
        "by the Pydantic schema. Writes to calc.audit_log and emits a SIEM event."
    ),
    responses={
        201: {"description": "Target created"},
        401: {"description": "Not authenticated"},
        403: {"description": "Requires admin role"},
        409: {"description": "Active target for this scope_coverage already exists"},
        422: {"description": "Payload failed domain invariant validation"},
    },
)
async def create_target(
    body: SbtiTargetCreate,
    request: Request,
    user: CurrentUser = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_db),
) -> SbtiTargetResponse:
    """Create a new SBTi reduction target.

    Args:
        body: Validated target payload.
        request: Raw request for IP and user-agent extraction.
        user: Authenticated admin.
        session: Async DB session.

    Returns:
        The newly created SbtiTargetResponse.

    Raises:
        HTTPException: 409 if an active target for this scope_coverage already exists.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub,
        tenant_id=user.tenant_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    tenant_uuid = uuid.UUID(user.tenant_id)

    # Check for existing active target on this scope_coverage (belt-and-suspenders
    # -- the partial UNIQUE index would catch it at the DB level too).
    existing_stmt = select(SbtiTarget).where(
        SbtiTarget.tenant_id == tenant_uuid,
        SbtiTarget.scope_coverage == body.scope_coverage,
        SbtiTarget.is_active.is_(True),
    )
    existing = (await session.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        raise _problem(
            status.HTTP_409_CONFLICT,
            "Conflict",
            (
                f"An active SBTi target for scope_coverage={body.scope_coverage!r} "
                f"already exists (id={existing.target_id}). "
                "Deactivate it before creating a new one."
            ),
            "sbti_target_scope_conflict",
            correlation_id,
        )

    reduction_pct = (
        (body.baseline_tco2e - body.target_tco2e) / body.baseline_tco2e * Decimal("100")
    ).quantize(Decimal("0.0001"))

    target_id = uuid.uuid4()
    now = datetime.now(tz=UTC)

    row = SbtiTarget(
        target_id=target_id,
        tenant_id=tenant_uuid,
        name=body.name,
        scope_coverage=body.scope_coverage,
        baseline_year=body.baseline_year,
        baseline_tco2e=body.baseline_tco2e,
        target_year=body.target_year,
        target_tco2e=body.target_tco2e,
        reduction_pct=reduction_pct,
        alignment=body.alignment,
        methodology=body.methodology,
        sbti_approval_status=body.sbti_approval_status,
        sbti_validation_date=body.sbti_validation_date,
        created_by=user.sub,
        created_at=now,
        is_active=True,
    )
    session.add(row)

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    session.add(
        AuditLog(
            tenant_id=tenant_uuid,
            correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
            user_role=user.role,
            action="sbti_target_created",
            resource="sbti_targets",
            resource_id=target_id,
            request_method="POST",
            request_path="/api/v1/sbti/targets",
            status_code=201,
            ip_address=client_ip,
            user_agent=user_agent,
            after_state={
                "name": body.name,
                "scope_coverage": body.scope_coverage,
                "baseline_year": body.baseline_year,
                "target_year": body.target_year,
                "alignment": body.alignment,
                "methodology": body.methodology,
                "sbti_approval_status": body.sbti_approval_status,
            },
        )
    )

    await session.flush()
    await session.refresh(row)

    log.info(
        "sbti_target_created",
        target_id=str(target_id),
        scope_coverage=body.scope_coverage,
        baseline_year=body.baseline_year,
        target_year=body.target_year,
    )

    siem.emit(
        event="sbti_target_created",
        correlation_id=correlation_id,
        tenant_id=user.tenant_id,
        user_sub=user.sub,
        severity="INFO",
        payload={
            "target_id": str(target_id),
            "scope_coverage": body.scope_coverage,
            "alignment": body.alignment,
        },
    )

    return _orm_to_response(row)


# ---------------------------------------------------------------------------
# PATCH /api/v1/sbti/targets/{target_id}/deactivate
# ---------------------------------------------------------------------------


@router.patch(
    "/targets/{target_id}/deactivate",
    response_model=SbtiTargetResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate an SBTi target (admin only)",
    description=(
        "Sets is_active=False on the specified target. This is the ONLY mutation "
        "permitted on a target row; the DB trigger enforces this. Writes to "
        "calc.audit_log and emits a SIEM event."
    ),
    responses={
        200: {"description": "Target deactivated"},
        401: {"description": "Not authenticated"},
        403: {"description": "Requires admin role"},
        404: {"description": "Target not found in this tenant"},
        409: {"description": "Target is already inactive"},
    },
)
async def deactivate_target(
    target_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_db),
) -> SbtiTargetResponse:
    """Deactivate an SBTi target (is_active True -> False).

    Args:
        target_id: UUID from the URL path.
        request: Raw request for IP and user-agent extraction.
        user: Authenticated admin.
        session: Async DB session.

    Returns:
        The updated SbtiTargetResponse with is_active=False.

    Raises:
        HTTPException: 404 if target not found in this tenant.
        HTTPException: 409 if already inactive.
    """
    correlation_id = get_correlation_id()
    tenant_uuid = uuid.UUID(user.tenant_id)
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub,
        target_id=str(target_id),
    )

    row = await _fetch_target_or_404(session, target_id, tenant_uuid, correlation_id)

    if not row.is_active:
        raise _problem(
            status.HTTP_409_CONFLICT,
            "Conflict",
            f"SBTi target {target_id} is already inactive.",
            "sbti_target_already_inactive",
            correlation_id,
        )

    stmt = (
        update(SbtiTarget)
        .where(
            SbtiTarget.target_id == target_id,
            SbtiTarget.tenant_id == tenant_uuid,
            SbtiTarget.is_active.is_(True),
        )
        .values(is_active=False)
    )
    result = await session.execute(stmt)
    if result.rowcount != 1:
        raise _problem(
            status.HTTP_409_CONFLICT,
            "Conflict",
            f"SBTi target {target_id} could not be deactivated (concurrent update).",
            "sbti_target_deactivate_race",
            correlation_id,
        )

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    session.add(
        AuditLog(
            tenant_id=tenant_uuid,
            correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
            user_role=user.role,
            action="sbti_target_deactivated",
            resource="sbti_targets",
            resource_id=target_id,
            request_method="PATCH",
            request_path=f"/api/v1/sbti/targets/{target_id}/deactivate",
            status_code=200,
            ip_address=client_ip,
            user_agent=user_agent,
            before_state={"is_active": True},
            after_state={"is_active": False},
        )
    )

    await session.flush()
    await session.refresh(row)

    log.info("sbti_target_deactivated", target_id=str(target_id))

    siem.emit(
        event="sbti_target_deactivated",
        correlation_id=correlation_id,
        tenant_id=user.tenant_id,
        user_sub=user.sub,
        severity="INFO",
        payload={"target_id": str(target_id)},
    )

    return _orm_to_response(row)


# ---------------------------------------------------------------------------
# GET /api/v1/sbti/targets/{target_id}/trajectory
# ---------------------------------------------------------------------------


@router.get(
    "/targets/{target_id}/trajectory",
    response_model=TrajectoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Trajectory and actuals for an SBTi target",
    description=(
        "Computes the linear ACA trajectory between baseline and target year, "
        "then loads actual consolidated emissions for the matched scopes. "
        "Returns a traffic-light status (ON_TRACK / SLIGHTLY_OFF / OFF_TRACK / NO_DATA). "
        "All authenticated roles may access this endpoint."
    ),
    responses={
        200: {"description": "Trajectory with actuals and status"},
        401: {"description": "Not authenticated"},
        404: {"description": "Target not found in this tenant"},
    },
)
async def get_trajectory(
    target_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission("sbti_targets", "read")),
    session: AsyncSession = Depends(get_db),
) -> TrajectoryResponse:
    """Return the computed trajectory plus actuals for a target.

    Args:
        target_id: UUID from the URL path.
        user: Authenticated user (any role).
        session: Async DB session.

    Returns:
        TrajectoryResponse with target metadata, status, and trajectory list.

    Raises:
        HTTPException: 404 if target not found in this tenant.
    """
    correlation_id = get_correlation_id()
    tenant_uuid = uuid.UUID(user.tenant_id)

    row = await _fetch_target_or_404(session, target_id, tenant_uuid, correlation_id)
    domain_target = _orm_to_domain(row)

    actual_by_year = await _load_actuals(
        session,
        tenant_uuid,
        row.scope_coverage,
        int(row.baseline_year),
        int(row.target_year),
    )

    trajectory_points = compute_trajectory(
        baseline_year=domain_target.baseline_year,
        baseline_tco2e=domain_target.baseline_tco2e,
        target_year=domain_target.target_year,
        target_tco2e=domain_target.target_tco2e,
    )
    annotated = annotate_actuals(trajectory_points, actual_by_year)

    tgt_status: TargetStatus = assess_status(
        target=domain_target,
        actual_by_year=actual_by_year,
    )

    logger.bind(
        correlation_id=correlation_id,
        user=user.sub,
    ).info(
        "sbti_trajectory_computed",
        target_id=str(target_id),
        status=tgt_status.value,
        years_with_data=len(actual_by_year),
    )

    return TrajectoryResponse(
        target=_orm_to_response(row),
        status=tgt_status.value,
        trajectory=[
            TrajectoryPointResponse(
                year=pt.year,
                trajectory_tco2e=pt.trajectory_tco2e,
                actual_tco2e=pt.actual_tco2e,
            )
            for pt in annotated
        ],
    )


# ---------------------------------------------------------------------------
# C-007: explicit 405 DELETE handler -- SBTi targets are append-only.
# Pattern mirrors emissions.py and chart_annotations.py.
# ---------------------------------------------------------------------------


@router.delete(
    "/targets/{target_id}",
    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
    summary="DELETE not allowed -- SBTi targets are append-only",
    description=(
        "SBTi targets are immutable once created. "
        "Use PATCH /targets/{id}/deactivate to deactivate a target."
    ),
    responses={405: {"description": "Method not allowed"}},
)
async def delete_sbti_target_not_allowed(target_id: uuid.UUID) -> dict[str, str]:
    """Return 405 for DELETE on SBTi targets.

    C-007: The append-only invariant is enforced at the API layer.  Returns
    a machine-readable detail string so clients can surface the correct action.
    """
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="SBTi targets are append-only; use deactivation",
    )

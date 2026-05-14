"""Chart annotations router -- M17 dashboard narrative overlays.

Endpoints:
  POST  /api/v1/chart-annotations               Create annotation (data_steward, esg_manager).
  GET   /api/v1/chart-annotations               List annotations for a chart_key (all roles).
  PATCH /api/v1/chart-annotations/{id}/visibility  Toggle is_visible (data_steward, esg_manager).
  PATCH /api/v1/chart-annotations/{id}/acknowledge Acknowledge annotation (esg_manager only).

Immutability invariants (ISAE 3000):
  - Rows are append-only. No DELETE endpoint is exposed.
  - After insert the DB trigger ``trg_chart_annotations_immutability`` permits
    only ``is_visible``, ``acknowledged_by``, and ``acknowledged_at`` to change.
    Any attempt to mutate frozen columns (body, title, chart_key, etc.) is
    rejected by the trigger with a PL/pgSQL RAISE EXCEPTION; this surfaces as
    asyncpg.exceptions.RaiseException which we map to HTTP 409.
  - ``tenant_id`` is always sourced from the JWT; never from the request body.
  - ``created_by`` is always the JWT ``sub`` claim.

include_hidden visibility rule:
  Only ``esg_manager`` and ``auditor`` may pass ``include_hidden=true``.
  ``data_steward`` always sees only visible annotations (is_visible=true).
  Rationale: data_steward is an operational role and does not need to inspect
  hidden audit trail entries; auditors and managers do for ISAE 3000 reviews.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission, require_role
from ghg_tool.infrastructure.db.models.chart_annotation import ChartAnnotation

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/chart-annotations", tags=["chart-annotations"])

# ---------------------------------------------------------------------------
# Allowed severity values -- validated here in addition to the DB CHECK
# constraint (defence in depth, ISAE 3000 SG-01).
# ---------------------------------------------------------------------------
_VALID_SEVERITIES: frozenset[str] = frozenset({"INFO", "WARNING", "CRITICAL"})

# Roles permitted to see hidden annotations.
_CAN_SEE_HIDDEN: frozenset[str] = frozenset({"esg_manager", "auditor"})


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class AnnotationCreate(BaseModel):
    """Request body for POST /api/v1/chart-annotations.

    Attributes:
        chart_key: Logical chart identifier (e.g. 'drilldown_scope').
        anchor_year: Optional year the annotation is attached to.
        anchor_label: Optional free-text label (e.g. 'Q3 kiln outage').
        title: Short annotation title (max 120 chars).
        body: Full narrative text (max 2000 chars).
        severity: INFO (default), WARNING, or CRITICAL.
        extra: Optional freeform JSON metadata.
    """

    model_config = ConfigDict(extra="forbid")

    chart_key: str = Field(min_length=1, max_length=80)
    anchor_year: int | None = Field(default=None, ge=2000, le=2100)
    anchor_label: str | None = Field(default=None, max_length=80)
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=2000)
    severity: str = Field(default="INFO")
    extra: dict[str, Any] | None = Field(default=None)

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, v: str) -> str:
        """Reject severity values not in the canonical set.

        Args:
            v: The severity string from the request body.

        Returns:
            The validated, uppercased severity string.

        Raises:
            ValueError: If the value is not INFO, WARNING, or CRITICAL.
        """
        upper = v.upper()
        if upper not in _VALID_SEVERITIES:
            raise ValueError(
                f"severity must be one of {sorted(_VALID_SEVERITIES)}"
            )
        return upper

    @field_validator("chart_key")
    @classmethod
    def _validate_chart_key(cls, v: str) -> str:
        """Accept only alphanumeric, dash, and underscore characters.

        Args:
            v: The chart_key string.

        Returns:
            The chart_key unchanged.

        Raises:
            ValueError: If the key contains disallowed characters.
        """
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "chart_key must be alphanumeric (hyphens and underscores allowed)"
            )
        return v


class VisibilityUpdate(BaseModel):
    """Request body for PATCH .../visibility.

    Attributes:
        is_visible: New visibility flag.
    """

    model_config = ConfigDict(extra="forbid")

    is_visible: bool


class AnnotationResponse(BaseModel):
    """Wire representation of a chart annotation row.

    UUIDs are serialised as strings for JSON compatibility with all clients.

    Attributes:
        id: Row UUID.
        tenant_id: Tenant UUID (string).
        chart_key: Logical chart identifier.
        anchor_year: Optional year anchor.
        anchor_label: Optional label anchor.
        title: Short title.
        body: Full narrative.
        severity: INFO | WARNING | CRITICAL.
        created_at: UTC timestamp of insertion.
        created_by: UUID of the creating user (JWT sub).
        is_visible: Visibility flag.
        acknowledged_by: UUID of the acknowledging user, or None.
        acknowledged_at: UTC timestamp of acknowledgement, or None.
        extra: Optional JSON metadata.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    chart_key: str
    anchor_year: int | None
    anchor_label: str | None
    title: str
    body: str
    severity: str
    created_at: datetime
    created_by: str
    is_visible: bool
    acknowledged_by: str | None
    acknowledged_at: datetime | None
    extra: dict[str, Any] | None

    @classmethod
    def from_orm_row(cls, row: ChartAnnotation) -> AnnotationResponse:
        """Build the response from an ORM row, converting UUIDs to strings.

        Args:
            row: The SQLAlchemy ORM instance.

        Returns:
            A populated ``AnnotationResponse``.
        """
        return cls(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            chart_key=row.chart_key,
            anchor_year=row.anchor_year,
            anchor_label=row.anchor_label,
            title=row.title,
            body=row.body,
            severity=row.severity,
            created_at=row.created_at,
            created_by=row.created_by,
            is_visible=row.is_visible,
            acknowledged_by=row.acknowledged_by,
            acknowledged_at=row.acknowledged_at,
            extra=row.extra,
        )


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
    """Build an RFC 7807-style HTTPException.

    Args:
        http_status: HTTP status code.
        title: Short problem title.
        detail: Human-readable explanation.
        error_code: Machine-readable slug.
        correlation_id: Request trace ID.

    Returns:
        An ``HTTPException`` with a problem+json body.
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


async def _fetch_annotation_or_404(
    session: AsyncSession,
    annotation_id: uuid.UUID,
    tenant_id: uuid.UUID,
    correlation_id: str,
) -> ChartAnnotation:
    """Load a chart annotation by PK within the caller's tenant or raise 404.

    Args:
        session: Active async DB session.
        annotation_id: Annotation UUID from the URL path.
        tenant_id: Tenant UUID from the JWT.
        correlation_id: Request trace ID for error responses.

    Returns:
        The matching ``ChartAnnotation`` ORM row.

    Raises:
        HTTPException: 404 if not found or belongs to a different tenant.
    """
    stmt = select(ChartAnnotation).where(
        ChartAnnotation.id == annotation_id,
        ChartAnnotation.tenant_id == tenant_id,
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            "Not Found",
            f"Chart annotation {annotation_id} not found in this tenant.",
            "chart_annotation_not_found",
            correlation_id,
        )
    return row


# ---------------------------------------------------------------------------
# POST /api/v1/chart-annotations
# ---------------------------------------------------------------------------


@router.post(
    "/",
    response_model=AnnotationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a chart annotation (append-only)",
    description=(
        "Appends a new narrative annotation to a dashboard chart. "
        "The ``tenant_id`` is derived from the JWT; ``created_by`` is the JWT sub. "
        "Rows are frozen post-insert except for ``is_visible`` and "
        "``acknowledged_*`` columns (DB trigger enforces this). "
        "Roles: data_steward, esg_manager."
    ),
    responses={
        201: {"description": "Annotation created"},
        401: {"description": "Not authenticated"},
        403: {"description": "Requires data_steward or esg_manager role"},
        422: {"description": "Payload validation failed"},
    },
)
async def create_annotation(
    body: AnnotationCreate,
    user: CurrentUser = Depends(require_permission("chart_annotations", "write")),
    session: AsyncSession = Depends(get_db),
) -> AnnotationResponse:
    """Create a new chart annotation.

    Args:
        body: Validated annotation payload.
        user: Authenticated user (data_steward or esg_manager).
        session: Async DB session with RLS GUCs set.

    Returns:
        The newly created ``AnnotationResponse``.

    Raises:
        HTTPException: 403 if the caller lacks write permission.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub,
        tenant_id=user.tenant_id,
        chart_key=body.chart_key,
    )

    tenant_uuid = uuid.UUID(user.tenant_id)
    annotation_id = uuid.uuid4()
    now = datetime.now(tz=UTC)

    row = ChartAnnotation(
        id=annotation_id,
        tenant_id=tenant_uuid,
        chart_key=body.chart_key,
        anchor_year=body.anchor_year,
        anchor_label=body.anchor_label,
        title=body.title,
        body=body.body,
        severity=body.severity,
        created_at=now,
        created_by=user.sub,
        is_visible=True,
        acknowledged_by=None,
        acknowledged_at=None,
        extra=body.extra,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)

    log.info(
        "chart_annotation_created",
        annotation_id=str(annotation_id),
        severity=body.severity,
        anchor_year=body.anchor_year,
    )

    return AnnotationResponse.from_orm_row(row)


# ---------------------------------------------------------------------------
# GET /api/v1/chart-annotations
# ---------------------------------------------------------------------------


@router.get(
    "/",
    response_model=list[AnnotationResponse],
    status_code=status.HTTP_200_OK,
    summary="List annotations for a chart key",
    description=(
        "Returns annotations filtered by ``chart_key`` (required) and optionally "
        "``anchor_year``. By default only ``is_visible=true`` rows are returned. "
        "``include_hidden=true`` is restricted to esg_manager and auditor roles. "
        "``data_steward`` always receives only visible annotations. "
        "Roles: all authenticated."
    ),
    responses={
        200: {"description": "List of annotations"},
        400: {"description": "chart_key is required"},
        401: {"description": "Not authenticated"},
        403: {"description": "include_hidden=true requires esg_manager or auditor role"},
    },
)
async def list_annotations(
    chart_key: Annotated[str, Query(min_length=1, max_length=80)],
    anchor_year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    include_hidden: Annotated[bool, Query()] = False,
    user: CurrentUser = Depends(require_permission("chart_annotations", "read")),
    session: AsyncSession = Depends(get_db),
) -> list[AnnotationResponse]:
    """List chart annotations for a given chart key.

    Args:
        chart_key: Required logical chart identifier to filter by.
        anchor_year: Optional year filter.
        include_hidden: When True, include is_visible=False rows. Requires
            esg_manager or auditor role.
        user: Authenticated user (any role).
        session: Async DB session with RLS GUCs set.

    Returns:
        List of matching ``AnnotationResponse`` objects ordered by
        ``created_at`` descending.

    Raises:
        HTTPException: 403 if data_steward requests include_hidden=true.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub,
        chart_key=chart_key,
    )

    if include_hidden and user.role not in _CAN_SEE_HIDDEN:
        raise _problem(
            status.HTTP_403_FORBIDDEN,
            "Forbidden",
            "include_hidden=true requires esg_manager or auditor role.",
            "insufficient_role_for_hidden",
            correlation_id,
        )

    tenant_uuid = uuid.UUID(user.tenant_id)

    stmt = select(ChartAnnotation).where(
        ChartAnnotation.tenant_id == tenant_uuid,
        ChartAnnotation.chart_key == chart_key,
    )

    if not include_hidden:
        stmt = stmt.where(ChartAnnotation.is_visible.is_(True))

    if anchor_year is not None:
        stmt = stmt.where(ChartAnnotation.anchor_year == anchor_year)

    stmt = stmt.order_by(ChartAnnotation.created_at.desc())

    result = await session.execute(stmt)
    rows = result.scalars().all()

    log.info(
        "chart_annotations_listed",
        count=len(rows),
        include_hidden=include_hidden,
        anchor_year=anchor_year,
    )

    return [AnnotationResponse.from_orm_row(r) for r in rows]


# ---------------------------------------------------------------------------
# PATCH /api/v1/chart-annotations/{id}/visibility
# ---------------------------------------------------------------------------


@router.patch(
    "/{annotation_id}/visibility",
    response_model=AnnotationResponse,
    status_code=status.HTTP_200_OK,
    summary="Toggle annotation visibility",
    description=(
        "Updates only ``is_visible`` on the specified annotation. "
        "The DB trigger permits this mutation; attempts to change any other "
        "frozen column would raise a 409. "
        "Roles: data_steward, esg_manager."
    ),
    responses={
        200: {"description": "Visibility updated"},
        401: {"description": "Not authenticated"},
        403: {"description": "Requires data_steward or esg_manager role"},
        404: {"description": "Annotation not found in this tenant"},
        409: {"description": "DB trigger blocked the mutation (frozen column)"},
    },
)
async def patch_visibility(
    annotation_id: uuid.UUID,
    body: VisibilityUpdate,
    user: CurrentUser = Depends(require_permission("chart_annotations", "write")),
    session: AsyncSession = Depends(get_db),
) -> AnnotationResponse:
    """Update the ``is_visible`` flag on a chart annotation.

    Args:
        annotation_id: UUID from the URL path.
        body: Visibility payload with ``is_visible`` boolean.
        user: Authenticated user (data_steward or esg_manager).
        session: Async DB session with RLS GUCs set.

    Returns:
        The updated ``AnnotationResponse``.

    Raises:
        HTTPException: 404 if not found in this tenant.
        HTTPException: 409 if the DB trigger blocks the update.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub,
        annotation_id=str(annotation_id),
    )

    tenant_uuid = uuid.UUID(user.tenant_id)
    row = await _fetch_annotation_or_404(session, annotation_id, tenant_uuid, correlation_id)

    try:
        row.is_visible = body.is_visible
        await session.flush()
        await session.refresh(row)
    except Exception as exc:  # noqa: BLE001
        _handle_db_trigger_error(exc, correlation_id)

    log.info(
        "chart_annotation_visibility_updated",
        annotation_id=str(annotation_id),
        is_visible=body.is_visible,
    )

    return AnnotationResponse.from_orm_row(row)


# ---------------------------------------------------------------------------
# PATCH /api/v1/chart-annotations/{id}/acknowledge
# ---------------------------------------------------------------------------


@router.patch(
    "/{annotation_id}/acknowledge",
    response_model=AnnotationResponse,
    status_code=status.HTTP_200_OK,
    summary="Acknowledge an annotation (esg_manager only)",
    description=(
        "Sets ``acknowledged_by`` to the JWT sub claim and ``acknowledged_at`` "
        "to the current UTC time. Returns 409 if the annotation has already been "
        "acknowledged. "
        "Role: esg_manager only."
    ),
    responses={
        200: {"description": "Annotation acknowledged"},
        401: {"description": "Not authenticated"},
        403: {"description": "Requires esg_manager role"},
        404: {"description": "Annotation not found in this tenant"},
        409: {"description": "Already acknowledged"},
    },
)
async def acknowledge_annotation(
    annotation_id: uuid.UUID,
    user: CurrentUser = Depends(require_role("esg_manager")),
    session: AsyncSession = Depends(get_db),
) -> AnnotationResponse:
    """Acknowledge a chart annotation.

    Sets ``acknowledged_by`` and ``acknowledged_at`` if not already set.

    Args:
        annotation_id: UUID from the URL path.
        user: Authenticated esg_manager.
        session: Async DB session with RLS GUCs set.

    Returns:
        The updated ``AnnotationResponse`` with acknowledgement fields set.

    Raises:
        HTTPException: 404 if not found in this tenant.
        HTTPException: 409 if the annotation was already acknowledged.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub,
        annotation_id=str(annotation_id),
    )

    tenant_uuid = uuid.UUID(user.tenant_id)
    row = await _fetch_annotation_or_404(session, annotation_id, tenant_uuid, correlation_id)

    if row.acknowledged_by is not None:
        raise _problem(
            status.HTTP_409_CONFLICT,
            "Conflict",
            f"Annotation {annotation_id} has already been acknowledged "
            f"by {row.acknowledged_by}.",
            "chart_annotation_already_acknowledged",
            correlation_id,
        )

    try:
        row.acknowledged_by = user.sub
        row.acknowledged_at = datetime.now(tz=UTC)
        await session.flush()
        await session.refresh(row)
    except Exception as exc:  # noqa: BLE001
        _handle_db_trigger_error(exc, correlation_id)

    log.info("chart_annotation_acknowledged", annotation_id=str(annotation_id))

    return AnnotationResponse.from_orm_row(row)


# ---------------------------------------------------------------------------
# Explicit 405 on DELETE (belt-and-suspenders documentation of append-only)
# ---------------------------------------------------------------------------


@router.delete(
    "/{annotation_id}",
    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
    summary="Delete is not permitted (append-only)",
    description=(
        "Chart annotations are append-only for ISAE 3000 audit trail integrity. "
        "Use PATCH .../visibility to hide an annotation instead."
    ),
    responses={405: {"description": "Method not allowed"}},
    include_in_schema=True,
)
async def delete_annotation_405(annotation_id: uuid.UUID) -> None:
    """Reject DELETE requests with 405.

    Chart annotations are append-only. Use visibility toggling to hide rows.

    Args:
        annotation_id: UUID from the URL path (unused; provided for routing).

    Raises:
        HTTPException: Always 405.
    """
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail=(
            "Chart annotations are append-only (ISAE 3000 audit trail). "
            "Use PATCH /api/v1/chart-annotations/{id}/visibility to hide."
        ),
    )


# ---------------------------------------------------------------------------
# DB trigger error handler
# ---------------------------------------------------------------------------


def _handle_db_trigger_error(exc: Exception, correlation_id: str) -> None:
    """Inspect an exception from asyncpg and raise an appropriate HTTP error.

    The DB trigger ``trg_chart_annotations_immutability`` raises a PL/pgSQL
    exception when a frozen column mutation is attempted.  asyncpg surfaces
    this as ``asyncpg.exceptions.RaiseException``.  We also catch the generic
    ``Exception`` path so that any unexpected DB error is wrapped in a 409
    with a safe message (no stack trace to the client per NFR-09).

    Args:
        exc: The exception caught from the DB flush.
        correlation_id: Request trace ID for logging.

    Raises:
        HTTPException: 409 with error_code 'chart_annotation_immutable'.
    """
    exc_type = type(exc).__name__
    logger.bind(correlation_id=correlation_id).warning(
        "chart_annotation_db_trigger_error",
        exc_type=exc_type,
    )

    # asyncpg raises RaiseException or InternalClientError for trigger violations
    trigger_exc_names = {"RaiseException", "InternalClientError", "IntegrityError"}
    if any(name in exc_type for name in trigger_exc_names):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "about:blank",
                "title": "Conflict",
                "status": 409,
                "detail": (
                    "The DB trigger rejected this mutation. Frozen columns "
                    "(title, body, chart_key, etc.) cannot be changed post-insert. "
                    "Only is_visible and acknowledged_* may be updated."
                ),
                "error_code": "chart_annotation_immutable",
                "correlation_id": correlation_id,
            },
        )

    # Re-raise unknown exceptions so the global error handler wraps them as 500
    raise exc

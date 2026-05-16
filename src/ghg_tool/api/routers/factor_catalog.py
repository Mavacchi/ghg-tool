"""Factor catalog router - GET + POST for /api/v1/factor-catalog (FR-04).

Includes two-eyes approval workflow for factor publication (FR-12,
ISAE 3000 §A99): a draft factor requires a second admin to approve
before it can be published. The proposer and approver cannot be the same
user.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.dependencies.pagination import encode_cursor
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rate_limit import publish_limiter
from ghg_tool.api.middleware.rbac import require_permission
from ghg_tool.api.schemas.common import CursorPage
from ghg_tool.api.schemas.factor_schemas import (
    FactorCatalogCreate,
    FactorCatalogPublishRequest,
    FactorCatalogPublishResponse,
    FactorCatalogResponse,
    FactorCatalogUpdate,
    FactorFilter,
)
from ghg_tool.application.services.factor_publish_service import (
    FactorAlreadyPublishedError,
    FactorNullValueError,
    FactorNotFoundError,
    FactorPublishService,
    FactorTbcError,
    PublishRaceConflictError,
    PublishResultApprovalRequested,
    SelfApprovalCreatorError,
    SelfApprovalForbiddenError,
    UserContext,
)
from ghg_tool.infrastructure.db.models.audit_log import AuditLog
from ghg_tool.infrastructure.db.models.factor import FactorCatalog
from ghg_tool.infrastructure.db.models.factor_publish_approval import FactorPublishApproval
from ghg_tool.infrastructure.db.repositories.factor_catalog_repository import (
    FactorCatalogRepository,
)
from ghg_tool.infrastructure.security import siem

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/factor-catalog", tags=["factor-catalog"])


# ---------------------------------------------------------------------------
# Schemas for approval workflow responses
# ---------------------------------------------------------------------------

class ApprovalRequestedResponse(BaseModel):
    """Response body when a publish request creates a new approval row.

    Returned with HTTP 202 when the first admin calls /publish.

    Attributes:
        approval_id: UUID of the newly created approval row.
        message: Human-readable status message for the caller.
    """

    model_config = ConfigDict(frozen=True)

    approval_id: uuid.UUID
    message: str


class PendingApprovalItem(BaseModel):
    """One pending approval entry returned by the list endpoint.

    Attributes:
        approval_id: UUID of the approval row.
        factor_id: UUID of the factor awaiting approval.
        factor_string_id: String factor identifier (e.g. 'WTT_GAS_NAT_DEFRA_2025').
        proposed_by: UUID of the admin who proposed.
        proposed_at: Timestamp of the proposal.
        reason_code: The publish reason code supplied at proposal time.
    """

    model_config = ConfigDict(frozen=True)

    approval_id: uuid.UUID
    factor_id: uuid.UUID
    factor_string_id: str
    proposed_by: uuid.UUID
    proposed_at: datetime
    reason_code: str | None


class ApprovalRejectRequest(BaseModel):
    """Body for ``POST /api/v1/factor-catalog/approvals/{approval_uuid}/reject``.

    Attributes:
        rejection_reason: Mandatory explanation (10-2000 chars).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rejection_reason: str = Field(min_length=10, max_length=2000)


class ApprovalRejectResponse(BaseModel):
    """Response after a successful rejection.

    Attributes:
        approval_id: UUID of the rejected approval.
        decision: Always 'REJECTED'.
    """

    model_config = ConfigDict(frozen=True)

    approval_id: uuid.UUID
    decision: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _problem(
    status_code: int,
    title: str,
    detail: str,
    error_code: str,
    correlation_id: str | None,
) -> HTTPException:
    """Build an RFC 7807 problem+json HTTPException.

    Args:
        status_code: HTTP status code.
        title: Short title.
        detail: Human-readable detail message.
        error_code: Machine-readable error code.
        correlation_id: Request correlation UUID string.

    Returns:
        HTTPException with RFC 7807 body.
    """
    return HTTPException(
        status_code=status_code,
        detail={
            "type": "about:blank",
            "title": title,
            "status": status_code,
            "error_code": error_code,
            "detail": detail,
            "correlation_id": correlation_id,
        },
    )


# ---------------------------------------------------------------------------
# Publish pre-condition checks and execution logic live in FactorPublishService
# (src/ghg_tool/application/services/factor_publish_service.py).
# This router imports the service and maps domain errors to HTTP responses.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=CursorPage[FactorCatalogResponse],
    status_code=status.HTTP_200_OK,
    summary="List emission factors (filterable, cursor-paginated)",
    description=(
        "Returns factor catalog entries. Filterable by scope, source, gwp_set, "
        "is_published, and factor_id. All authenticated roles may read."
    ),
    responses={
        200: {"description": "Factor catalog entries"},
        401: {"description": "Not authenticated"},
    },
)
async def list_factors(
    filters: Annotated[FactorFilter, Depends()],
    user: CurrentUser = Depends(require_permission("factor_catalog", "read")),
    session: AsyncSession = Depends(get_db),
) -> CursorPage[FactorCatalogResponse]:
    """Return a paginated list of factor catalog entries.

    Args:
        filters: Query parameter filter values.
        user: Authenticated user with factor_catalog:read permission.
        session: Authenticated DB session.

    Returns:
        Paginated factor catalog rows.
    """
    correlation_id = get_correlation_id()
    logger.bind(correlation_id=correlation_id).info("list_factors")

    stmt = select(FactorCatalog).where(
        FactorCatalog.tenant_id == uuid.UUID(user.tenant_id)
    )
    if filters.scope is not None:
        stmt = stmt.where(FactorCatalog.scope == filters.scope)
    if filters.source is not None:
        stmt = stmt.where(FactorCatalog.source == filters.source)
    if filters.gwp_set is not None:
        stmt = stmt.where(FactorCatalog.gwp_set == filters.gwp_set)
    if filters.is_published is not None:
        stmt = stmt.where(FactorCatalog.is_published == filters.is_published)
    if filters.factor_id is not None:
        stmt = stmt.where(FactorCatalog.factor_id == filters.factor_id)
    stmt = stmt.limit(filters.limit + 1)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    items = [FactorCatalogResponse.model_validate(r) for r in rows[: filters.limit]]
    next_cursor: str | None = None
    if len(rows) > filters.limit:
        next_cursor = encode_cursor(rows[filters.limit - 1].id)

    return CursorPage(items=items, next_cursor=next_cursor)


# ---------------------------------------------------------------------------
# GET /{factor_id}/versions
# ---------------------------------------------------------------------------

@router.get(
    "/{factor_id}/versions",
    response_model=list[FactorCatalogResponse],
    status_code=status.HTTP_200_OK,
    summary="List all versions of a specific factor",
    description="Returns full version history (all published/unpublished rows) for a factor_id.",
    responses={
        200: {"description": "Version history"},
        401: {"description": "Not authenticated"},
    },
)
async def list_factor_versions(
    factor_id: str,
    user: CurrentUser = Depends(require_permission("factor_catalog", "read")),
    session: AsyncSession = Depends(get_db),
) -> list[FactorCatalogResponse]:
    """Return all versions of a specific factor_id string.

    Args:
        factor_id: The string factor identifier (e.g. 'WTT_GAS_NAT_DEFRA_2025').
        user: Authenticated user with factor_catalog:read permission.
        session: Authenticated DB session.

    Returns:
        List of all versions ordered by valid_from desc.
    """
    stmt = (
        select(FactorCatalog)
        .where(
            FactorCatalog.tenant_id == uuid.UUID(user.tenant_id),
            FactorCatalog.factor_id == factor_id,
        )
        .order_by(FactorCatalog.valid_from.desc())
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [FactorCatalogResponse.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# POST /
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=FactorCatalogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new factor version (editor only, pre-publish only)",
    description=(
        "Creates a new version of a factor entry. Once published (is_published=True), "
        "the DB trigger makes the row immutable (MG-02). editor role only."
    ),
    responses={
        201: {"description": "Factor created"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role - editor required"},
        422: {"description": "Validation error"},
    },
)
async def create_factor(
    body: FactorCatalogCreate,
    user: CurrentUser = Depends(require_permission("factor_catalog", "write")),
    session: AsyncSession = Depends(get_db),
) -> FactorCatalogResponse:
    """Create a new factor catalog entry (editor only).

    Args:
        body: Validated ``FactorCatalogCreate`` payload.
        user: Authenticated editor user.
        session: Authenticated DB session.

    Returns:
        The created ``FactorCatalogResponse``.

    Raises:
        HTTPException: 403 if role is not editor.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    log.info("create_factor", factor_id=body.factor_id, version=body.version)

    repo = FactorCatalogRepository(session)
    new_factor = FactorCatalog(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(user.tenant_id),
        factor_id=body.factor_id,
        version=body.version,
        substance=body.substance,
        scope=body.scope,
        category=body.category,
        source=body.source,
        value=body.value,
        is_licence_only=body.is_licence_only,
        unit=body.unit,
        gwp_set=body.gwp_set,
        vintage=body.vintage,
        valid_from=body.valid_from,
        applicability_note=body.applicability_note,
        pdf_source_uri=body.pdf_source_uri,
        biogenic_co2_kg_per_unit=body.biogenic_co2_kg_per_unit,
        # MG-03: draft rows must have published_at=None and published_by=None.
        # Both columns are nullable after migration 0010_M9.  created_at is
        # set by the DB server_default (func.now()); do not pass it here.
        published_at=None,
        published_by=None,
        # C-004: set created_by from the authenticated user sub.
        created_by=uuid.UUID(user.sub),
        is_published=False,
        is_tbc=False,
    )
    persisted = await repo.insert(new_factor)
    log.info("Factor created", factor_db_id=str(persisted.id))
    return FactorCatalogResponse.model_validate(persisted)


# ---------------------------------------------------------------------------
# GET /pending-approvals  (must be declared BEFORE /{uuid}/publish to avoid
# FastAPI treating "pending-approvals" as a path parameter value)
# ---------------------------------------------------------------------------

@router.get(
    "/pending-approvals",
    response_model=list[PendingApprovalItem],
    status_code=status.HTTP_200_OK,
    summary="List pending factor publish approvals (admin only)",
    description=(
        "Returns all factor approval requests in the PENDING state for the "
        "caller's tenant. admin only."
    ),
    responses={
        200: {"description": "List of pending approvals"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role - admin required"},
    },
)
async def list_pending_approvals(
    user: CurrentUser = Depends(require_permission("factor_catalog", "approve")),
    session: AsyncSession = Depends(get_db),
) -> list[PendingApprovalItem]:
    """Return all PENDING approval rows for the caller's tenant.

    Joins to calc.factor_catalog to include the human-readable factor_id
    string alongside the UUID.

    Args:
        user: Authenticated admin from JWT.
        session: Async DB session.

    Returns:
        List of ``PendingApprovalItem`` records.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(
        correlation_id=correlation_id,
        tenant_id=user.tenant_id,
        user=user.sub[:8],
    )
    log.info("list_pending_approvals")

    result = await session.execute(
        text(
            "SELECT a.id, a.factor_id, f.factor_id AS factor_string_id, "
            "       a.proposed_by, a.proposed_at, a.reason_code "
            "FROM calc.factor_publish_approvals a "
            "JOIN ref.factor_catalog f ON f.id = a.factor_id "
            "WHERE a.tenant_id = CAST(:tenant AS uuid) "
            "  AND a.decision = 'PENDING' "
            "ORDER BY a.proposed_at ASC"
        ),
        {"tenant": user.tenant_id},
    )
    rows = result.fetchall()
    return [
        PendingApprovalItem(
            approval_id=row.id,
            factor_id=row.factor_id,
            factor_string_id=row.factor_string_id,
            proposed_by=row.proposed_by,
            proposed_at=row.proposed_at,
            reason_code=row.reason_code,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# POST /approvals/{approval_uuid}/reject
# ---------------------------------------------------------------------------

@router.post(
    "/approvals/{approval_uuid}/reject",
    response_model=ApprovalRejectResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject a pending factor publish approval (admin only)",
    description=(
        "Marks the approval as REJECTED with mandatory decision_notes. "
        "The factor remains in DRAFT state. Writes an audit_log row and "
        "emits a SIEM event at severity WARN."
    ),
    responses={
        200: {"description": "Approval rejected, factor remains DRAFT"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role - admin required"},
        404: {"description": "Approval not found or belongs to a different tenant"},
        422: {"description": "rejection_reason too short (min 10 chars)"},
    },
)
async def reject_approval(
    approval_uuid: uuid.UUID,
    request: Request,
    body: ApprovalRejectRequest,
    user: CurrentUser = Depends(require_permission("factor_catalog", "approve")),
    session: AsyncSession = Depends(get_db),
) -> ApprovalRejectResponse:
    """Reject a PENDING approval; factor stays in DRAFT.

    Args:
        approval_uuid: UUID of the approval row from the URL path.
        request: HTTP request (for audit metadata).
        body: ``ApprovalRejectRequest`` with mandatory rejection_reason.
        user: Authenticated admin from JWT.
        session: Async DB session.

    Returns:
        ``ApprovalRejectResponse`` confirming the rejection.

    Raises:
        HTTPException: 404 if not found or belongs to a different tenant.
        HTTPException: 409 if the approval is not in PENDING state.
    """
    correlation_id = get_correlation_id()
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log = logger.bind(
        correlation_id=correlation_id,
        tenant_id=user.tenant_id,
        user=user.sub[:8],
        ip_address=client_ip,
        user_agent=user_agent,
        approval_uuid=str(approval_uuid),
    )

    stmt = select(FactorPublishApproval).where(
        FactorPublishApproval.id == approval_uuid,
        FactorPublishApproval.tenant_id == uuid.UUID(user.tenant_id),
    )
    result = await session.execute(stmt)
    approval = result.scalar_one_or_none()

    if approval is None:
        log.warning("reject_approval_not_found")
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            "Not Found",
            f"Approval {approval_uuid} not found.",
            "approval_not_found",
            correlation_id,
        )

    if approval.decision != "PENDING":
        log.warning("reject_approval_not_pending", decision=approval.decision)
        raise _problem(
            status.HTTP_409_CONFLICT,
            "Conflict",
            f"Approval {approval_uuid} is already {approval.decision} and cannot be rejected.",
            "approval_not_pending",
            correlation_id,
        )

    now_utc = datetime.now(tz=UTC)
    approval.decision = "REJECTED"
    approval.approved_by = uuid.UUID(user.sub)
    approval.approved_at = now_utc
    approval.decision_notes = body.rejection_reason

    session.add(
        AuditLog(
            tenant_id=uuid.UUID(user.tenant_id),
            correlation_id=uuid.UUID(correlation_id),
            user_role=user.role,
            action="factor_approval_rejected",
            resource="factor_catalog",
            resource_id=approval.factor_id,
            request_method="POST",
            request_path=f"/api/v1/factor-catalog/approvals/{approval_uuid}/reject",
            status_code=200,
            ip_address=client_ip,
            user_agent=user_agent,
            after_state={
                "approval_id": str(approval_uuid),
                "decision": "REJECTED",
                "rejected_by": user.sub,
                "rejected_at": now_utc.isoformat(),
            },
        )
    )

    await session.flush()

    log.info(
        "factor_approval_rejected",
        approval_id=str(approval_uuid),
        factor_id=str(approval.factor_id),
    )

    siem.emit(
        event="factor_approval_rejected",
        correlation_id=correlation_id,
        tenant_id=user.tenant_id,
        user_sub=user.sub,
        severity="WARN",
        payload={
            "approval_id": str(approval_uuid),
            "factor_id": str(approval.factor_id),
        },
    )

    return ApprovalRejectResponse(approval_id=approval_uuid, decision="REJECTED")


# ---------------------------------------------------------------------------
# POST /{factor_uuid}/publish  (two-eyes workflow)
# ---------------------------------------------------------------------------

@router.post(
    "/{factor_uuid}/publish",
    status_code=status.HTTP_200_OK,
    summary="Publish a draft factor - two-eyes approval (admin only)",
    description=(
        "Implements the ISAE 3000 §A99 two-eyes principle:\n\n"
        "1. First admin calls /publish -> 202: approval row created "
        "(PENDING), reason_code captured.\n"
        "2. Same admin calls /publish again -> 409 self_approval_forbidden.\n"
        "3. Different admin calls /publish -> 200: factor published, "
        "approval marked APPROVED.\n"
        "4. If already APPROVED (published) -> 409 already_published.\n\n"
        "The body's ``reason_code`` is captured on the INITIAL call only; "
        "the second call's body is accepted but reason_code is ignored.\n\n"
        "**Rate limit**: 10 publish calls per user per minute."
    ),
    responses={
        200: {"description": "Factor published (second admin approved)"},
        202: {"description": "Approval requested, awaiting second admin"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role - admin required"},
        404: {"description": "Factor not found or belongs to a different tenant"},
        409: {
            "description": (
                "self_approval_forbidden: same proposer cannot approve; "
                "already_published: factor already published."
            )
        },
        422: {"description": "Factor cannot be published: is_tbc=True or value=NULL"},
    },
)
async def publish_factor(
    factor_uuid: uuid.UUID,
    request: Request,
    body: FactorCatalogPublishRequest,
    user: CurrentUser = Depends(require_permission("factor_catalog", "publish")),
    session: AsyncSession = Depends(get_db),
) -> Any:
    """Two-eyes approval publish endpoint — HTTP orchestration only.

    Business logic is delegated to FactorPublishService. This handler:
    1. Checks rate limit.
    2. Calls service.publish() and receives a typed PublishResult.
    3. Maps PublishResult (or domain errors) to HTTP responses.

    Args:
        factor_uuid: UUID primary key of the draft factor row.
        request: HTTP request (for audit metadata).
        body: Required publish payload with ``reason_code`` + optional notes.
        user: Authenticated admin from JWT.
        session: Async DB session.

    Returns:
        ``ApprovalRequestedResponse`` (202) or ``FactorCatalogPublishResponse`` (200).
    """
    correlation_id = get_correlation_id()
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub[:8],
        tenant_id=user.tenant_id,
        ip_address=client_ip,
        user_agent=user_agent,
        factor_uuid=str(factor_uuid),
    )

    if not publish_limiter.is_allowed(f"publish:user:{user.sub}"):
        log.warning("publish_factor_rate_limited")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "type": "about:blank",
                "title": "Too Many Requests",
                "status": 429,
                "detail": "Factor publication rate limit exceeded: 10 per minute per user.",
                "correlation_id": correlation_id,
            },
        )

    service = FactorPublishService(session=session)
    user_ctx = UserContext.from_current_user(user)

    try:
        result = await service.publish(
            factor_uuid,
            body,
            user=user_ctx,
            correlation_id=correlation_id,
            client_ip=client_ip,
            user_agent=user_agent,
        )
    except FactorNotFoundError:
        log.warning("publish_factor_not_found")
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            "Not Found",
            f"Factor {factor_uuid} not found.",
            "factor_not_found",
            correlation_id,
        )
    except FactorAlreadyPublishedError as exc:
        log.warning("publish_factor_already_published")
        raise _problem(
            status.HTTP_409_CONFLICT,
            "Conflict",
            (
                f"Factor {exc.factor_id}/{exc.version} is already published "
                "and immutable. No action taken."
            ),
            "already_published",
            correlation_id,
        )
    except FactorTbcError as exc:
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unprocessable Entity",
            (
                f"Factor {exc.factor_id}/{exc.version} is marked as TBC "
                "(to-be-confirmed). Pin the numeric value before publishing."
            ),
            "tbc_factor",
            correlation_id,
        )
    except FactorNullValueError as exc:
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unprocessable Entity",
            (
                f"Factor {exc.factor_id}/{exc.version} has a NULL value "
                "but is_licence_only=False. Set a numeric value or mark as "
                "is_licence_only before publishing."
            ),
            "null_value",
            correlation_id,
        )
    except SelfApprovalForbiddenError:
        log.warning("publish_factor_self_approval_blocked")
        raise _problem(
            status.HTTP_409_CONFLICT,
            "Conflict",
            (
                "The same admin who proposed the approval cannot also "
                "approve it (ISAE 3000 two-eyes principle)."
            ),
            "self_approval_forbidden",
            correlation_id,
        )
    except SelfApprovalCreatorError:
        raise _problem(
            status.HTTP_409_CONFLICT,
            "Conflict",
            "The factor creator cannot also approve publication (ISAE 3000).",
            "self_approval_creator",
            correlation_id,
        )
    except PublishRaceConflictError as exc:
        raise _problem(
            status.HTTP_409_CONFLICT,
            "Conflict",
            (
                f"Factor {exc.factor_id}/{exc.version} was published "
                "by another user concurrently. No action taken."
            ),
            "already_published",
            correlation_id,
        )

    # Map typed result to HTTP response.
    if isinstance(result, PublishResultApprovalRequested):
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "approval_id": str(result.approval_id),
                "message": "Approval requested, awaiting second admin",
            },
        )
    # PublishResultPublished -> 200
    return result.factor_response


# ---------------------------------------------------------------------------
# PATCH /{factor_uuid}  — edit draft factor fields
# ---------------------------------------------------------------------------

@router.patch(
    "/{factor_uuid}",
    response_model=FactorCatalogResponse,
    status_code=status.HTTP_200_OK,
    summary="Update mutable fields on a DRAFT factor (editor only)",
    description=(
        "Allows partial updates to a factor catalog entry **before** it is "
        "published.  Send only the fields you want to change.\n\n"
        "**Immutability**: published rows (``is_published=True``) are protected "
        "by both the DB trigger ``trg_factor_immutable`` (MG-02) and an "
        "app-layer guard that returns 422 ``factor_already_published`` before "
        "any SQL UPDATE is attempted.  This guarantees that audit-trail "
        "integrity per ADR-007 / ISAE 3000 §A99 is maintained even if the "
        "trigger is temporarily disabled.\n\n"
        "Identity fields (``factor_id``, ``version``, ``gwp_set``, ``source``, "
        "``substance``, ``scope``, ``category``) are not patchable.  Create a "
        "new version instead."
    ),
    responses={
        200: {"description": "Factor updated; returns the full updated row."},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role - editor required"},
        404: {"description": "Factor not found or belongs to a different tenant"},
        422: {"description": "factor_already_published: row is immutable per ADR-007"},
    },
)
async def patch_factor(
    factor_uuid: uuid.UUID,
    request: Request,
    body: FactorCatalogUpdate,
    user: CurrentUser = Depends(require_permission("factor_catalog", "write")),
    session: AsyncSession = Depends(get_db),
) -> FactorCatalogResponse:
    """Partial update of a DRAFT factor row.

    Args:
        factor_uuid: UUID primary key of the target factor row.
        request: HTTP request (for audit metadata).
        body: ``FactorCatalogUpdate`` payload; all fields optional.
        user: Authenticated editor user.
        session: Async DB session.

    Returns:
        The updated ``FactorCatalogResponse``.

    Raises:
        HTTPException: 404 if factor not found or tenant mismatch.
        HTTPException: 422 if factor is already published.
    """
    correlation_id = get_correlation_id()
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub[:8],
        tenant_id=user.tenant_id,
        factor_uuid=str(factor_uuid),
    )
    log.info("patch_factor_draft")

    repo = FactorCatalogRepository(session)
    factor = await repo.get_by_uuid(
        tenant_id=uuid.UUID(user.tenant_id),
        factor_uuid=factor_uuid,
    )

    if factor is None:
        log.warning("patch_factor_not_found")
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            "Not Found",
            f"Factor {factor_uuid} not found.",
            "factor_not_found",
            correlation_id,
        )

    # App-layer immutability guard (ADR-007).  The DB trigger is the last line
    # of defence, but we raise 422 here to give the caller a machine-readable
    # error code before touching the DB.
    if factor.is_published:
        log.warning("patch_factor_already_published")
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unprocessable Entity",
            (
                f"Factor {factor.factor_id}/{factor.version} is already published "
                "and immutable per ADR-007. Use the correction workflow instead."
            ),
            "factor_already_published",
            correlation_id,
        )

    # Capture before-state for audit log.
    before_state: dict[str, Any] = {
        "value": float(factor.value) if factor.value is not None else None,
        "unit": factor.unit,
        "applicability_note": factor.applicability_note,
        "pdf_source_uri": factor.pdf_source_uri,
        "biogenic_co2_kg_per_unit": (
            float(factor.biogenic_co2_kg_per_unit)
            if factor.biogenic_co2_kg_per_unit is not None
            else None
        ),
        "is_licence_only": factor.is_licence_only,
        "is_tbc": factor.is_tbc,
        "vintage": factor.vintage,
        "valid_from": factor.valid_from.isoformat() if factor.valid_from else None,
    }

    # Apply only the fields explicitly provided in the body.
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(factor, field, value)

    await session.flush()

    after_state: dict[str, Any] = {
        "value": float(factor.value) if factor.value is not None else None,
        "unit": factor.unit,
        "applicability_note": factor.applicability_note,
        "pdf_source_uri": factor.pdf_source_uri,
        "biogenic_co2_kg_per_unit": (
            float(factor.biogenic_co2_kg_per_unit)
            if factor.biogenic_co2_kg_per_unit is not None
            else None
        ),
        "is_licence_only": factor.is_licence_only,
        "is_tbc": factor.is_tbc,
        "vintage": factor.vintage,
        "valid_from": factor.valid_from.isoformat() if factor.valid_from else None,
        "updated_by": user.sub,
    }

    session.add(
        AuditLog(
            tenant_id=uuid.UUID(user.tenant_id),
            correlation_id=uuid.UUID(correlation_id),
            user_role=user.role,
            action="factor_draft_updated",
            resource="factor_catalog",
            resource_id=factor.id,
            request_method="PATCH",
            request_path=f"/api/v1/factor-catalog/{factor_uuid}",
            status_code=200,
            ip_address=client_ip,
            user_agent=user_agent,
            before_state=before_state,
            after_state=after_state,
        )
    )
    await session.flush()

    log.info(
        "factor_draft_updated",
        factor_id=factor.factor_id,
        version=factor.version,
        fields_changed=list(update_data.keys()),
    )

    return FactorCatalogResponse.model_validate(factor)


# ---------------------------------------------------------------------------
# DELETE /{factor_uuid}  — remove draft factor
# ---------------------------------------------------------------------------

@router.delete(
    "/{factor_uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a DRAFT factor row (editor only)",
    description=(
        "Permanently removes a factor catalog entry that has **not yet been "
        "published** (``is_published=False``).\n\n"
        "**Immutability**: published rows (``is_published=True``) are protected "
        "by both the DB trigger ``trg_factor_immutable`` (MG-02) and an "
        "app-layer guard that returns 422 ``factor_already_published``.  "
        "Published rows are never hard-deleted; use the correction workflow "
        "to supersede them.\n\n"
        "Writes an audit_log row on success.  Returns 204 No Content."
    ),
    responses={
        204: {"description": "Factor deleted successfully."},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role - editor required"},
        404: {"description": "Factor not found or belongs to a different tenant"},
        422: {"description": "factor_already_published: row is immutable per ADR-007"},
    },
)
async def delete_factor(
    factor_uuid: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require_permission("factor_catalog", "write")),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete a DRAFT factor row (editor only).

    Args:
        factor_uuid: UUID primary key of the target factor row.
        request: HTTP request (for audit metadata).
        user: Authenticated editor user.
        session: Async DB session.

    Returns:
        None (204 No Content).

    Raises:
        HTTPException: 404 if factor not found or tenant mismatch.
        HTTPException: 422 if factor is already published.
    """
    correlation_id = get_correlation_id()
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub[:8],
        tenant_id=user.tenant_id,
        factor_uuid=str(factor_uuid),
    )
    log.info("delete_factor_draft")

    repo = FactorCatalogRepository(session)
    factor = await repo.get_by_uuid(
        tenant_id=uuid.UUID(user.tenant_id),
        factor_uuid=factor_uuid,
    )

    if factor is None:
        log.warning("delete_factor_not_found")
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            "Not Found",
            f"Factor {factor_uuid} not found.",
            "factor_not_found",
            correlation_id,
        )

    # App-layer immutability guard (ADR-007).
    if factor.is_published:
        log.warning("delete_factor_already_published")
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unprocessable Entity",
            (
                f"Factor {factor.factor_id}/{factor.version} is already published "
                "and immutable per ADR-007. Published rows cannot be deleted."
            ),
            "factor_already_published",
            correlation_id,
        )

    before_state: dict[str, Any] = {
        "factor_id": factor.factor_id,
        "version": factor.version,
        "gwp_set": factor.gwp_set,
        "source": factor.source,
        "scope": factor.scope,
        "is_published": factor.is_published,
        "deleted_by": user.sub,
    }

    await session.delete(factor)

    session.add(
        AuditLog(
            tenant_id=uuid.UUID(user.tenant_id),
            correlation_id=uuid.UUID(correlation_id),
            user_role=user.role,
            action="factor_draft_deleted",
            resource="factor_catalog",
            resource_id=factor_uuid,
            request_method="DELETE",
            request_path=f"/api/v1/factor-catalog/{factor_uuid}",
            status_code=204,
            ip_address=client_ip,
            user_agent=user_agent,
            before_state=before_state,
            after_state=None,
        )
    )
    await session.flush()

    log.info(
        "factor_draft_deleted",
        factor_id=factor.factor_id,
        version=factor.version,
    )

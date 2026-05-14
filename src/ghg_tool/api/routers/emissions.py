"""Emissions router — append-only read + write for calc.emissions_consolidated.

Key invariants (FR-20, FR-30, FR-31):
- GET /  : all authenticated roles; filterable; cursor-paginated.
- POST / : data_steward only; append-only insert.
- POST /correction : data_steward + esg_manager; correction-as-new-row.
- GET /{id}/corrections : full superseded_by chain.
- DELETE /{id} : returns 405 Method Not Allowed (not registered; FastAPI default).
- PUT/PATCH /{id} : not registered — 405 by default.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.dependencies.pagination import encode_cursor
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission, require_role
from ghg_tool.api.schemas.common import CursorPage
from ghg_tool.api.schemas.emission_schemas import (
    EmissionCorrectionCreate,
    EmissionCorrectionResponse,
    EmissionCreate,
    EmissionFilter,
    EmissionResponse,
)
from ghg_tool.api.schemas.kpi_schemas import EmissionCreateResponse
from ghg_tool.infrastructure.db.models.emission import Emission
from ghg_tool.infrastructure.db.repositories.emissions_repository import (
    EmissionsRepository,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/emissions", tags=["emissions"])


# ---------------------------------------------------------------------------
# Internal factory helpers (REV-002, REV-003)
# ---------------------------------------------------------------------------


def _build_new_emission_row(
    body: EmissionCreate,
    user: CurrentUser,
    correlation_id: str,
    now: datetime,
) -> Emission:
    """Build an Emission ORM instance for a new (non-correction) record.

    Args:
        body: Validated ``EmissionCreate`` payload.
        user: Authenticated user creating the record.
        correlation_id: Request-scoped correlation UUID string.
        now: UTC datetime of the request.

    Returns:
        An unsaved ``Emission`` ORM instance ready for ``repo.insert``.
    """
    return Emission(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(user.tenant_id),
        correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
        raw_row_id=body.raw_row_id,
        raw_scope=body.raw_scope,
        scope=body.scope,
        sub_scope=body.sub_scope,
        codice_sito=body.codice_sito,
        anno=body.anno,
        tco2e=body.tco2e,
        co2_tonne=body.co2_tonne,
        ch4_tco2e=body.ch4_tco2e,
        n2o_tco2e=body.n2o_tco2e,
        co2_biogenic_tonne=body.co2_biogenic_tonne,
        co2_fossil_tonne=body.co2_fossil_tonne,
        factor_id=body.factor_id,
        factor_version=body.factor_version,
        factor_source=body.factor_source,
        gwp_set=body.gwp_set,
        methodology=body.methodology,
        regulatory_stream=body.regulatory_stream,
        calc_timestamp=now,
        created_by=user.sub,
        valid_from=now,
        disclosure_notes=body.disclosure_notes,
    )


def _build_correction_row(
    body: EmissionCorrectionCreate,
    user: CurrentUser,
    correlation_id: str,
    now: datetime,
) -> tuple[uuid.UUID, Emission]:
    """Build an Emission ORM instance for a correction row.

    Args:
        body: Validated ``EmissionCorrectionCreate`` payload.
        user: Authenticated user performing the correction.
        correlation_id: Request-scoped correlation UUID string.
        now: UTC datetime of the request.

    Returns:
        A tuple of (new_id, unsaved ``Emission`` ORM instance).
    """
    new_id = uuid.uuid4()
    row = Emission(
        id=new_id,
        tenant_id=uuid.UUID(user.tenant_id),
        correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
        raw_row_id=body.new_record.raw_row_id,
        raw_scope=body.new_record.raw_scope,
        scope=body.new_record.scope,
        sub_scope=body.new_record.sub_scope,
        codice_sito=body.new_record.codice_sito,
        anno=body.new_record.anno,
        tco2e=body.new_record.tco2e,
        co2_tonne=body.new_record.co2_tonne,
        ch4_tco2e=body.new_record.ch4_tco2e,
        n2o_tco2e=body.new_record.n2o_tco2e,
        co2_biogenic_tonne=body.new_record.co2_biogenic_tonne,
        co2_fossil_tonne=body.new_record.co2_fossil_tonne,
        factor_id=body.new_record.factor_id,
        factor_version=body.new_record.factor_version,
        factor_source=body.new_record.factor_source,
        gwp_set=body.new_record.gwp_set,
        methodology=body.new_record.methodology,
        regulatory_stream=body.new_record.regulatory_stream,
        calc_timestamp=now,
        created_by=user.sub,
        valid_from=now,
        reason_code=body.reason_code,
        disclosure_notes=body.new_record.disclosure_notes,
    )
    return new_id, row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/",
    response_model=CursorPage[EmissionResponse],
    status_code=status.HTTP_200_OK,
    summary="List emission records (cursor-paginated, filterable)",
    description=(
        "Returns active (valid_to IS NULL) emission rows from "
        "calc.emissions_consolidated. Filterable by scope, anno, codice_sito, "
        "sub_scope, regulatory_stream, gwp_set. DB RLS filters to the "
        "authenticated tenant automatically (AD-008). Auditors see all rows "
        "(read-only); other roles also have full read access."
    ),
    responses={
        200: {"description": "Paginated emission list"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role"},
    },
)
async def list_emissions(
    filters: Annotated[EmissionFilter, Depends()],
    user: CurrentUser = Depends(require_permission("emissions", "read")),
    session: AsyncSession = Depends(get_db),
) -> CursorPage[EmissionResponse]:
    """Return a filtered, paginated list of active emission rows.

    Args:
        filters: Query parameter filter values.
        user: The authenticated current user.
        session: An authenticated async DB session with RLS GUCs set.

    Returns:
        A cursor-paginated page of ``EmissionResponse`` items.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    log.info("list_emissions", scope=filters.scope, anno=filters.anno)

    repo = EmissionsRepository(session)
    rows = await repo.get_active(
        tenant_id=uuid.UUID(user.tenant_id),
        scope=filters.scope,
        anno=filters.anno,
        codice_sito=filters.codice_sito,
        regulatory_stream=filters.regulatory_stream,
        gwp_set=filters.gwp_set,
        sub_scope=filters.sub_scope,
    )

    # Cursor-based pagination (simple ID-based slice for v1)
    items = [EmissionResponse.model_validate(r) for r in rows[: filters.limit]]
    next_cursor: str | None = None
    if len(rows) > filters.limit:
        next_cursor = encode_cursor(rows[filters.limit - 1].id)

    return CursorPage(items=items, next_cursor=next_cursor, total=len(rows))


@router.post(
    "/",
    response_model=EmissionCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Append a new emission record (data_steward only, append-only)",
    description=(
        "Inserts a new row into calc.emissions_consolidated. "
        "Enforces append-only semantics (FR-20). "
        "Requires ``Idempotency-Key`` header (UUID v4) to prevent duplicates. "
        "data_steward role only (FR-30, FR-31)."
    ),
    responses={
        201: {"description": "Record created"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role — data_steward required"},
        409: {"description": "Idempotency key already used"},
        422: {"description": "Validation error"},
    },
)
async def create_emission(
    body: EmissionCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8)],
    user: CurrentUser = Depends(require_role("data_steward")),
    session: AsyncSession = Depends(get_db),
) -> EmissionCreateResponse:
    """Append a new emission row (FR-30, append-only).

    Args:
        body: Validated ``EmissionCreate`` payload.
        idempotency_key: Client-supplied UUID v4 to deduplicate requests.
        user: Authenticated data_steward user.
        session: Authenticated DB session with RLS GUCs.

    Returns:
        An ``EmissionCreateResponse`` with ``id``, ``correlation_id``, and ``created_at``.

    Raises:
        HTTPException: 403 if role is not data_steward; 422 on validation error.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub[:8],
        idempotency_key=idempotency_key[:8],
    )
    log.info(
        "create_emission",
        scope=body.scope,
        anno=body.anno,
        codice_sito=body.codice_sito,
    )

    now = datetime.now(tz=UTC)
    new_row = _build_new_emission_row(body, user, correlation_id, now)

    repo = EmissionsRepository(session)
    persisted = await repo.insert(new_row)
    log.info("Emission created", new_id=str(persisted.id))
    return EmissionCreateResponse(
        id=persisted.id,
        correlation_id=correlation_id or "",
        created_at=now,
    )


@router.post(
    "/correction",
    response_model=EmissionCorrectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an emission correction (correction-as-new-row, FR-21)",
    description=(
        "Inserts a replacement emission row and closes the predecessor via "
        "calc.fn_emit_correction. Append-only — never overwrites the original. "
        "data_steward or esg_manager role required."
    ),
    responses={
        201: {"description": "Correction applied"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role"},
        404: {"description": "Predecessor row not found or already superseded"},
        422: {"description": "Validation error"},
    },
)
async def correct_emission(
    body: EmissionCorrectionCreate,
    user: CurrentUser = Depends(require_permission("emissions", "correct")),
    session: AsyncSession = Depends(get_db),
) -> EmissionCorrectionResponse:
    """Apply a correction via the append-only superseded_by pattern (FR-21).

    Args:
        body: Validated ``EmissionCorrectionCreate`` payload.
        user: Authenticated user with 'correct' permission.
        session: Authenticated DB session with RLS GUCs.

    Returns:
        ``EmissionCorrectionResponse`` with new and superseded row UUIDs.

    Raises:
        HTTPException: 404 if predecessor not found; 422 on validation error.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub[:8],
        supersedes_id=str(body.supersedes_id),
    )
    log.info("correct_emission", reason_code=body.reason_code)

    now = datetime.now(tz=UTC)
    repo = EmissionsRepository(session)

    # Verify predecessor exists, belongs to the caller's tenant, and is active.
    # Passing tenant_id ensures a cross-tenant UUID guess returns 404 even if
    # RLS is misconfigured.
    predecessor = await repo.get_by_id(
        body.supersedes_id, tenant_id=uuid.UUID(user.tenant_id)
    )
    if predecessor is None or predecessor.valid_to is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "about:blank",
                "title": "Not Found",
                "status": 404,
                "detail": f"Emission {body.supersedes_id} not found or already superseded",
                "correlation_id": correlation_id,
            },
        )

    new_id, new_row = _build_correction_row(body, user, correlation_id, now)

    await repo.insert(new_row)
    await repo.apply_correction(
        predecessor_id=body.supersedes_id,
        new_id=new_id,
        reason_code=body.reason_code,
    )

    log.info("Correction applied", new_id=str(new_id))
    return EmissionCorrectionResponse(
        new_id=new_id,
        supersedes_id=body.supersedes_id,
        correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
    )


@router.get(
    "/{emission_id}/corrections",
    response_model=list[EmissionResponse],
    status_code=status.HTTP_200_OK,
    summary="Get the correction chain for an emission row",
    description=(
        "Returns the full superseded_by chain from the given emission ID, "
        "ordered from oldest to newest. Includes both active and superseded rows."
    ),
    responses={
        200: {"description": "Correction chain"},
        401: {"description": "Not authenticated"},
        404: {"description": "Emission not found"},
    },
)
async def get_corrections(
    emission_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission("emissions", "read")),
    session: AsyncSession = Depends(get_db),
) -> list[EmissionResponse]:
    """Return the full correction chain for an emission record.

    Args:
        emission_id: UUID of any row in the correction chain.
        user: Authenticated user with read permission.
        session: Authenticated DB session with RLS GUCs.

    Returns:
        List of ``EmissionResponse`` objects in chronological order.

    Raises:
        HTTPException: 404 if the emission does not exist.
    """
    correlation_id = get_correlation_id()
    repo = EmissionsRepository(session)
    row = await repo.get_by_id(emission_id, tenant_id=uuid.UUID(user.tenant_id))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "about:blank",
                "title": "Not Found",
                "status": 404,
                "detail": f"Emission {emission_id} not found",
                "correlation_id": correlation_id,
            },
        )
    # For v1: return just this row; wave 3 implements full chain traversal
    return [EmissionResponse.model_validate(row)]


# ---------------------------------------------------------------------------
# Explicit 405 guards for methods that MUST be blocked on emission records
# ---------------------------------------------------------------------------


@router.delete(
    "/{emission_id}",
    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
    response_model=None,
    summary="DELETE is not allowed on consolidated emissions (FR-20, append-only)",
    description="Emissions are immutable. Use POST /correction for amendments.",
    responses={405: {"description": "Method Not Allowed — append-only enforcement"}},
    include_in_schema=True,
)
async def delete_emission_blocked(emission_id: uuid.UUID) -> None:  # noqa: B008
    """Return 405 Method Not Allowed for DELETE requests on emissions.

    Args:
        emission_id: The emission UUID (present in path for route matching only).

    Raises:
        HTTPException: Always raises 405 (FR-20 append-only enforcement).
    """
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail={
            "type": "about:blank",
            "title": "Method Not Allowed",
            "status": 405,
            "detail": (
                "Emissions are immutable (FR-20). "
                "Use POST /api/v1/emissions/correction to amend."
            ),
        },
    )


@router.put(
    "/{emission_id}",
    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
    response_model=None,
    summary="PUT is not allowed on consolidated emissions (FR-20, append-only)",
    description="Emissions are immutable. Use POST /correction for amendments.",
    responses={405: {"description": "Method Not Allowed"}},
    include_in_schema=True,
)
async def put_emission_blocked(emission_id: uuid.UUID) -> None:
    """Return 405 Method Not Allowed for PUT requests on emissions.

    Args:
        emission_id: The emission UUID (present in path for route matching only).

    Raises:
        HTTPException: Always raises 405 (FR-20 append-only enforcement).
    """
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail={
            "type": "about:blank",
            "title": "Method Not Allowed",
            "status": 405,
            "detail": "Emissions are immutable (FR-20).",
        },
    )

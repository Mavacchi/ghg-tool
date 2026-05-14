"""Factor catalog router — GET + POST for /api/v1/factor-catalog (FR-04)."""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.dependencies.pagination import encode_cursor
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission
from ghg_tool.api.schemas.common import CursorPage
from ghg_tool.api.schemas.factor_schemas import (
    FactorCatalogCreate,
    FactorCatalogResponse,
    FactorFilter,
)
from ghg_tool.infrastructure.db.models.factor import FactorCatalog
from ghg_tool.infrastructure.db.repositories.factor_catalog_repository import (
    FactorCatalogRepository,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/factor-catalog", tags=["factor-catalog"])


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


@router.post(
    "/",
    response_model=FactorCatalogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new factor version (data_steward only, pre-publish only)",
    description=(
        "Creates a new version of a factor entry. Once published (is_published=True), "
        "the DB trigger makes the row immutable (MG-02). data_steward role only."
    ),
    responses={
        201: {"description": "Factor created"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role — data_steward required"},
        422: {"description": "Validation error"},
    },
)
async def create_factor(
    body: FactorCatalogCreate,
    user: CurrentUser = Depends(require_permission("factor_catalog", "write")),
    session: AsyncSession = Depends(get_db),
) -> FactorCatalogResponse:
    """Create a new factor catalog entry (data_steward only).

    Args:
        body: Validated ``FactorCatalogCreate`` payload.
        user: Authenticated data_steward user.
        session: Authenticated DB session.

    Returns:
        The created ``FactorCatalogResponse``.

    Raises:
        HTTPException: 403 if role is not data_steward.
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
        # ``published_by`` is NOT NULL at the DB level, so it must be set even
        # for drafts.  On creation it records the *creator* (the user who
        # proposed the factor); a future publish endpoint will overwrite it
        # with the actual publisher when ``is_published`` flips to True.  The
        # ``is_published=False`` flag below preserves the audit-trail
        # distinction between proposed and published factors.
        published_by=user.sub,
        is_published=False,
        is_tbc=False,
    )
    persisted = await repo.insert(new_factor)
    log.info("Factor created", factor_db_id=str(persisted.id))
    return FactorCatalogResponse.model_validate(persisted)

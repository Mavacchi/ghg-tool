"""Sites router — GET /api/v1/sites — list active production sites (FR-28).

Returns the tenant's active sites from ``ref.sites``.  The site list is used
by the Streamlit UI as the authoritative source of site codes, with fallback
to the ``GHG_SITES`` env var / built-in default when the API is unreachable.

RBAC: all authenticated roles may read (editor, admin, viewer).
Read-only: no POST / PUT / DELETE on ``/api/v1/sites``.

SEC-P0-003 — Cross-tenant isolation:
  tenant_id is sourced exclusively from the validated JWT claim.
  No client-supplied tenant filter is accepted.

Migration M6 (0026) adds ``site_type`` (STABILIMENTO_PRODUTTIVO | UFFICIO |
MAGAZZINO) and ``country`` (CHAR(2), default 'IT') to ``ref.sites``.  Both
columns are exposed here since M6 is required on the target branch.
"""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/sites", tags=["sites"])

# Site-type literal aligned with the DB ENUM introduced in migration M6.
SiteType = Literal["STABILIMENTO_PRODUTTIVO", "UFFICIO", "MAGAZZINO"]


class SiteOut(BaseModel):
    """A single active production site (M6-extended schema).

    Attributes:
        codice_sito: Site code (e.g. ``IANO``, ``VIANO``).
        full_name: Human-readable full name of the site.
        role: Operational role of the site (e.g. ``production``, ``logistics``).
        geography: ISO-3166 alpha-2 country code or region tag.
        country: ISO-3166 alpha-2 country code from ``ref.sites.country``
            (M6, decision #2).  Used for LB factor lookup; default ``'IT'``.
        site_type: Classification from M6 decision #7.  One of
            ``STABILIMENTO_PRODUTTIVO``, ``UFFICIO``, ``MAGAZZINO``.
            Validates Processo_Decarb applicability at the API level.
        eu_ets_installation_id: EU ETS installation identifier; ``None`` if not
            registered.
        is_active: Whether the site is within the current operational boundary.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    codice_sito: str
    full_name: str
    role: str
    geography: str
    country: str = Field(min_length=2, max_length=2)
    site_type: SiteType
    eu_ets_installation_id: str | None = None
    is_active: bool = True


# Keep the old name as an alias so existing callers that imported SiteRow
# continue to resolve without a NameError.
SiteRow = SiteOut


class SitesResponse(BaseModel):
    """Response envelope for ``GET /api/v1/sites``.

    Attributes:
        sites: List of active sites for the caller's tenant.
        tenant_id_prefix: First 8 characters of the JWT tenant UUID (for
            traceability without exposing the full UUID).
        correlation_id: Request-level correlation UUID (FR-22).
    """

    model_config = ConfigDict(frozen=True)

    sites: list[SiteOut] = Field(default_factory=list)
    tenant_id_prefix: str
    correlation_id: str


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
    summary="List active production sites for the caller's tenant",
    description=(
        "Returns all active rows from ``ref.sites`` for the tenant identified "
        "by the caller's JWT.  The result is the authoritative site list for "
        "the Streamlit UI; the ``GHG_SITES`` env var is a fallback for "
        "offline / pre-migration scenarios only.\n\n"
        "M6 fields: ``site_type`` (STABILIMENTO_PRODUTTIVO | UFFICIO | MAGAZZINO) "
        "and ``country`` (ISO-3166 alpha-2, default 'IT') are now included.\n\n"
        "SEC-P0-003: tenant isolation is enforced via the JWT claim — no "
        "client-supplied tenant filter is accepted."
    ),
    response_model=SitesResponse,
    responses={
        200: {"description": "Active sites for the caller's tenant"},
        401: {"description": "Not authenticated"},
        403: {"description": "Role not permitted"},
    },
)
async def get_sites(
    user: CurrentUser = Depends(require_permission("sites", "read")),
    session: AsyncSession = Depends(get_db),
) -> SitesResponse:
    """Return active sites for the caller's tenant.

    SEC-P0-003: tenant_id is sourced from the validated JWT claim, never from
    the query string.

    Args:
        user: Authenticated user; tenant_id is extracted from the JWT claim.
        session: Async DB session with RLS GUCs set by the auth middleware.

    Returns:
        A ``SitesResponse`` with the active sites for the tenant (M6 schema).
    """
    tenant_id = user.tenant_id
    correlation_id = get_correlation_id() or ""

    log = logger.bind(
        correlation_id=correlation_id,
        tenant_id=tenant_id[:8],
    )
    log.info("get_sites")

    result = await session.execute(
        text(
            "SELECT codice_sito, full_name, role, geography, "
            "       country, site_type, "
            "       eu_ets_installation_id, is_active "
            "FROM ref.sites "
            "WHERE tenant_id = CAST(:tenant_id AS uuid) "
            "  AND is_active = TRUE "
            "ORDER BY codice_sito"
        ),
        {"tenant_id": tenant_id},
    )
    rows = [SiteOut(**dict(r._mapping)) for r in result]

    log.info("get_sites_ok", site_count=len(rows))

    return SitesResponse(
        sites=rows,
        tenant_id_prefix=tenant_id[:8],
        correlation_id=correlation_id,
    )

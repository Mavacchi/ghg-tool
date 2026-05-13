"""GO certificates router — /api/v1/go-certificates (methodology_validation §2.4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission
from ghg_tool.api.schemas.common import CursorPage
from ghg_tool.api.schemas.go_schemas import (
    GoCertificateCreate,
    GoCertificateResponse,
    GoFilter,
    GoValidationPatch,
)
from ghg_tool.infrastructure.db.models.go_certificate import GoCertificate

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/go-certificates", tags=["go-certificates"])


@router.get(
    "/",
    response_model=CursorPage[GoCertificateResponse],
    status_code=status.HTTP_200_OK,
    summary="List GO certificate evidence records",
    description=(
        "Returns GO certificate evidence rows from ref.go_certificate_evidence. "
        "Filterable by site_id, anno, all_qc_passed. All authenticated roles may read."
    ),
    responses={
        200: {"description": "GO certificate list"},
        401: {"description": "Not authenticated"},
    },
)
async def list_go_certificates(
    filters: Annotated[GoFilter, Depends()],
    user: CurrentUser = Depends(require_permission("go_certificates", "read")),
    session: AsyncSession = Depends(get_db),
) -> CursorPage[GoCertificateResponse]:
    """Return a paginated list of GO certificate evidence records.

    Args:
        filters: Query parameter filter values.
        user: Authenticated user with go_certificates:read permission.
        session: Authenticated DB session.

    Returns:
        Paginated GO certificate records.
    """
    correlation_id = get_correlation_id()
    logger.bind(correlation_id=correlation_id).info("list_go_certificates")

    stmt = select(GoCertificate).where(
        GoCertificate.tenant_id == uuid.UUID(user.tenant_id)
    )
    if filters.site_id is not None:
        stmt = stmt.where(GoCertificate.site_id == filters.site_id)
    if filters.anno is not None:
        stmt = stmt.where(GoCertificate.anno == filters.anno)
    stmt = stmt.limit(filters.limit + 1)

    result = await session.execute(stmt)
    rows = result.scalars().all()

    # Filter all_qc_passed in Python (computed property)
    if filters.all_qc_passed is not None:
        rows = [
            r for r in rows
            if _all_qc(r) == filters.all_qc_passed
        ]

    items = [GoCertificateResponse.model_validate(r) for r in rows[: filters.limit]]
    next_cursor: str | None = None
    if len(rows) > filters.limit:
        from ghg_tool.api.dependencies.pagination import encode_cursor
        next_cursor = encode_cursor(rows[filters.limit - 1].id)

    return CursorPage(items=items, next_cursor=next_cursor)


@router.post(
    "/",
    response_model=GoCertificateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a GO certificate evidence record (data_steward only)",
    description=(
        "Creates a new GO certificate evidence row with QC1-QC8 boolean checks "
        "per GHG Protocol Scope 2 Quality Criteria (methodology_validation §2.4). "
        "data_steward role only."
    ),
    responses={
        201: {"description": "GO certificate created"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role — data_steward required"},
        422: {"description": "Validation error"},
    },
)
async def create_go_certificate(
    body: GoCertificateCreate,
    user: CurrentUser = Depends(require_permission("go_certificates", "write")),
    session: AsyncSession = Depends(get_db),
) -> GoCertificateResponse:
    """Create a new GO certificate evidence record.

    Args:
        body: Validated ``GoCertificateCreate`` payload.
        user: Authenticated data_steward user.
        session: Authenticated DB session.

    Returns:
        The created ``GoCertificateResponse``.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    log.info("create_go_certificate", go_id=body.go_id, anno=body.anno)

    new_cert = GoCertificate(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(user.tenant_id),
        go_id=body.go_id,
        site_id=body.site_id,
        anno=body.anno,
        volume_mwh=body.volume_mwh,
        vintage_year=body.vintage_year,
        cancellation_date=body.cancellation_date,
        beneficiary_legal_entity=body.beneficiary_legal_entity,
        country_of_issuance=body.country_of_issuance,
        technology=body.technology,
        qc1_conveyed_claim_passed=body.qc1_conveyed_claim_passed,
        qc2_unique_passed=body.qc2_unique_passed,
        qc3_redeemed_passed=body.qc3_redeemed_passed,
        qc4_vintage_passed=body.qc4_vintage_passed,
        qc5_geographic_passed=body.qc5_geographic_passed,
        qc6_scope_passed=body.qc6_scope_passed,
        qc7_exclusivity_passed=body.qc7_exclusivity_passed,
        qc8_residual_mix_disclosed=body.qc8_residual_mix_disclosed,
        pdf_evidence_uri=body.pdf_evidence_uri,
        validated_by=user.sub,
        validated_at=datetime.now(tz=UTC),
    )
    session.add(new_cert)
    await session.flush()
    log.info("GO certificate created", cert_id=str(new_cert.id))
    return GoCertificateResponse.model_validate(new_cert)


@router.patch(
    "/{go_id}/validate",
    response_model=GoCertificateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new validation version for a GO certificate (append-only)",
    description=(
        "Creates a new GO certificate evidence row with the same go_id, updated QC checks, "
        "and a new validated_at timestamp. Append-only — never overwrites the original. "
        "data_steward role only."
    ),
    responses={
        201: {"description": "Validation version created"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role — data_steward required"},
        404: {"description": "GO certificate not found"},
    },
)
async def validate_go_certificate(
    go_id: str,
    body: GoValidationPatch,
    user: CurrentUser = Depends(require_permission("go_certificates", "validate")),
    session: AsyncSession = Depends(get_db),
) -> GoCertificateResponse:
    """Create a new validation version for an existing GO certificate (append-only).

    Fetches the most recent row for ``go_id``, merges the updated QC fields,
    and inserts a new row without modifying the original.

    Args:
        go_id: The GSE GO certificate identifier.
        body: ``GoValidationPatch`` with optional QC field overrides.
        user: Authenticated data_steward user.
        session: Authenticated DB session.

    Returns:
        The newly created validation version row.

    Raises:
        HTTPException: 404 if the go_id is not found.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    log.info("validate_go_certificate", go_id=go_id)

    result = await session.execute(
        select(GoCertificate)
        .where(
            GoCertificate.tenant_id == uuid.UUID(user.tenant_id),
            GoCertificate.go_id == go_id,
        )
        .order_by(GoCertificate.validated_at.desc())
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "about:blank",
                "title": "Not Found",
                "status": 404,
                "detail": f"GO certificate '{go_id}' not found",
                "correlation_id": correlation_id,
            },
        )

    def _pick(patch_val: bool | None, original: bool) -> bool:
        return patch_val if patch_val is not None else original

    new_cert = GoCertificate(
        id=uuid.uuid4(),
        tenant_id=existing.tenant_id,
        go_id=existing.go_id,
        site_id=existing.site_id,
        anno=existing.anno,
        volume_mwh=existing.volume_mwh,
        vintage_year=existing.vintage_year,
        cancellation_date=existing.cancellation_date,
        beneficiary_legal_entity=existing.beneficiary_legal_entity,
        country_of_issuance=existing.country_of_issuance,
        technology=existing.technology,
        qc1_conveyed_claim_passed=_pick(
            body.qc1_conveyed_claim_passed, existing.qc1_conveyed_claim_passed
        ),
        qc2_unique_passed=_pick(body.qc2_unique_passed, existing.qc2_unique_passed),
        qc3_redeemed_passed=_pick(body.qc3_redeemed_passed, existing.qc3_redeemed_passed),
        qc4_vintage_passed=_pick(body.qc4_vintage_passed, existing.qc4_vintage_passed),
        qc5_geographic_passed=_pick(
            body.qc5_geographic_passed, existing.qc5_geographic_passed
        ),
        qc6_scope_passed=_pick(body.qc6_scope_passed, existing.qc6_scope_passed),
        qc7_exclusivity_passed=_pick(
            body.qc7_exclusivity_passed, existing.qc7_exclusivity_passed
        ),
        qc8_residual_mix_disclosed=_pick(
            body.qc8_residual_mix_disclosed, existing.qc8_residual_mix_disclosed
        ),
        pdf_evidence_uri=body.pdf_evidence_uri or existing.pdf_evidence_uri,
        validated_by=user.sub,
        validated_at=datetime.now(tz=UTC),
    )
    session.add(new_cert)
    await session.flush()
    log.info("GO certificate validation version created", cert_id=str(new_cert.id))
    return GoCertificateResponse.model_validate(new_cert)


def _all_qc(cert: GoCertificate) -> bool:
    """Return True if all 8 QC booleans are True on the given DB row.

    Args:
        cert: The ORM ``GoCertificate`` instance.

    Returns:
        Boolean AND of all 8 QC fields.
    """
    return all([
        cert.qc1_conveyed_claim_passed,
        cert.qc2_unique_passed,
        cert.qc3_redeemed_passed,
        cert.qc4_vintage_passed,
        cert.qc5_geographic_passed,
        cert.qc6_scope_passed,
        cert.qc7_exclusivity_passed,
        cert.qc8_residual_mix_disclosed,
    ])

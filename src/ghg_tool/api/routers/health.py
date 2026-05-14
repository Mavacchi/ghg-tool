"""Health and readiness endpoints — no auth required.

``GET /healthz`` — liveness: always returns 200 if the process is running.
``GET /readyz`` — readiness: performs a minimal DB connectivity probe.

These endpoints are intentionally outside the ``/api/v1/`` prefix so that
Kubernetes/Docker health checks can reach them without a versioned path.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.db import get_db_no_auth

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get(
    "/healthz",
    summary="Liveness probe",
    description="Returns 200 OK if the API process is alive. No auth required.",
    responses={200: {"description": "Service is alive"}},
)
async def healthz() -> JSONResponse:
    """Liveness probe endpoint.

    Returns:
        200 OK with ``{\"status\": \"ok\"}`` body.
    """
    return JSONResponse({"status": "ok"})


@router.get(
    "/readyz",
    summary="Readiness probe",
    description=(
        "Returns 200 OK if the API can reach the database. "
        "Returns 503 if the DB is unreachable. No auth required."
    ),
    responses={
        200: {"description": "Service is ready"},
        503: {"description": "Database unreachable"},
    },
)
async def readyz(
    session: AsyncSession = Depends(get_db_no_auth),
) -> JSONResponse:
    """Readiness probe — checks database connectivity.

    Args:
        session: A bare DB session (no auth/GUCs) for the connectivity probe.

    Returns:
        200 OK if SELECT 1 succeeds; 503 if the DB is unreachable.
    """
    try:
        from sqlalchemy import text
        await session.execute(text("SELECT 1"))
        return JSONResponse({"status": "ready", "db": "ok"})
    except Exception as exc:  # noqa: BLE001
        logger.error("Readiness probe DB failure", error=str(exc))
        return JSONResponse(
            {"status": "not_ready", "db": "unreachable"},
            status_code=503,
        )

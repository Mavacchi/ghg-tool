"""FastAPI application entry point — GHG Accounting API.

Constructs the ``FastAPI`` app with:
- lifespan context for structured startup/shutdown logging
- RFC 7807 error handler middleware
- Correlation-ID middleware (FR-22)
- Rate-limit middleware (SG-10, NFR-11)
- 9 routers + health endpoints
- OpenAPI 3.1 metadata; Swagger UI available only in non-production

Environment variables consumed:
  GHG_ENVIRONMENT (default 'development') — disables /docs in production.
  GHG_JWT_ALGORITHM / GHG_JWT_SECRET / GHG_JWT_PUBLIC_KEY_PATH / … (see security.jwt)
  SQLALCHEMY_URL (default postgresql+asyncpg://… — see db/session.py)

NFR-09 A02: no stack traces in error responses.
NFR-08 / SG-07: no PII in logs; correlation_id on every entry.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ghg_tool.api.middleware.correlation_id import CorrelationIdMiddleware
from ghg_tool.api.middleware.error_handler import ErrorHandlerMiddleware
from ghg_tool.api.middleware.rate_limit import RateLimitMiddleware
from ghg_tool.api.routers import (
    audit_trail,
    auth,
    dq_findings,
    emissions,
    factor_catalog,
    go_certificates,
    health,
    kpis,
    reports,
)

logger = structlog.get_logger(__name__)

_ENVIRONMENT = os.environ.get("GHG_ENVIRONMENT", "development")
_VERSION = "0.1.0"

_PROBLEM_CONTENT_TYPE = "application/problem+json"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan context — startup and shutdown hooks.

    Args:
        app: The FastAPI application instance.

    Yields:
        Control to the request-handling loop.
    """
    logger.info(
        "GHG API starting",
        version=_VERSION,
        environment=_ENVIRONMENT,
    )
    yield
    logger.info("GHG API shutting down")


def _create_app() -> FastAPI:
    """Construct and configure the FastAPI application.

    Returns:
        A fully configured ``FastAPI`` instance.
    """
    docs_url = "/docs" if _ENVIRONMENT != "production" else None
    redoc_url = "/redoc" if _ENVIRONMENT != "production" else None

    app = FastAPI(
        title="GHG Accounting API",
        version=_VERSION,
        description=(
            "REST API for the GHG Accounting Tool — Italian ceramic-tile manufacturer. "
            "CSRD ESRS E1 + EU ETS Phase IV (IANO Annex I Activity 17). "
            "Append-only emission storage; JWT/RBAC; RFC 7807 error responses."
        ),
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url="/openapi.json",
        lifespan=_lifespan,
    )

    # ------------------------------------------------------------------
    # Middleware stack (applied in reverse — last added = outermost)
    # ------------------------------------------------------------------
    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    # ------------------------------------------------------------------
    # Custom exception handlers
    # ------------------------------------------------------------------
    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Convert Pydantic validation errors to RFC 7807 format.

        Args:
            request: The failing request.
            exc: The ``RequestValidationError`` raised by Pydantic.

        Returns:
            A 422 JSONResponse with ``application/problem+json`` content type.
        """
        from ghg_tool.api.middleware.correlation_id import get_correlation_id
        cid = get_correlation_id()

        def _safe_error(err: dict) -> dict:  # type: ignore[type-arg]
            """Strip non-serialisable / PII fields from a Pydantic error dict.

            Pydantic v2 ``exc.errors()`` may embed ``ValueError`` objects inside
            the ``ctx`` mapping and raw input values inside ``input``.  Both must
            be stripped before JSON serialisation (NFR-09 — no stack trace; NFR-08
            — no PII in responses).
            """
            out: dict = {}  # type: ignore[type-arg]
            for k, v in err.items():
                if k in ("input", "url"):
                    # Never echo request input back (may contain passwords/PII)
                    continue
                if k == "ctx":
                    # ctx values may be non-serialisable exception objects
                    out[k] = {ck: str(cv) for ck, cv in v.items()}
                else:
                    out[k] = v
            return out

        errors = [_safe_error(err) for err in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={
                "type": "about:blank",
                "title": "Unprocessable Entity",
                "status": 422,
                "detail": "Request body or query parameters failed validation",
                "errors": errors,
                "correlation_id": cid,
            },
            headers={"Content-Type": _PROBLEM_CONTENT_TYPE},
        )

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(emissions.router)
    app.include_router(kpis.router)
    app.include_router(audit_trail.router)
    app.include_router(factor_catalog.router)
    app.include_router(dq_findings.router)
    app.include_router(go_certificates.router)
    app.include_router(reports.router)

    return app


app = _create_app()

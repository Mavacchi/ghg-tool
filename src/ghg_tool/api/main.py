"""FastAPI application entry point — GHG Accounting API.

Constructs the ``FastAPI`` app with:
- lifespan context for structured startup/shutdown logging
- RFC 7807 error handler middleware
- Correlation-ID middleware (FR-22)
- Rate-limit middleware (SG-10, NFR-11)
- CORS middleware (SEC-P1-001) — origins from GHG_CORS_ORIGINS env var
- Security-headers middleware (SEC-P1-002) — HSTS, CSP, X-Frame-Options, …
- 10 routers + health endpoints
- OpenAPI 3.1 metadata; Swagger UI available only in non-production

Environment variables consumed:
  GHG_ENVIRONMENT (default 'development') — disables /docs in production.
  GHG_JWT_ALGORITHM / GHG_JWT_SECRET / GHG_JWT_PUBLIC_KEY_PATH / … (see security.jwt)
  GHG_CORS_ORIGINS — comma-separated HTTPS origins; empty = no CORS (SEC-P1-001).
    NEVER set to "*" in production. Example: https://dashboard.example.com
  SQLALCHEMY_URL (default postgresql+asyncpg://… — see db/session.py)

NFR-09 A02: no stack traces in error responses.
NFR-08 / SG-07: no PII in logs; correlation_id on every entry.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Final

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ghg_tool.api.middleware.correlation_id import CorrelationIdMiddleware
from ghg_tool.api.middleware.error_handler import ErrorHandlerMiddleware
from ghg_tool.api.middleware.rate_limit import RateLimitMiddleware
from ghg_tool.api.middleware.security_headers import SecurityHeadersMiddleware
from ghg_tool.api.routers import (
    audit_trail,
    auth,
    dq_findings,
    emissions,
    exports,
    factor_catalog,
    go_certificates,
    health,
    intensity,
    kpis,
    reports,
)

logger = structlog.get_logger(__name__)

_ENVIRONMENT = os.environ.get("GHG_ENVIRONMENT", "development")
_VERSION = "0.1.0"

_PROBLEM_CONTENT_TYPE = "application/problem+json"

# SEC-P1-001: CORS origins — comma-separated HTTPS origins from env.
# NEVER use ["*"] — wildcard CORS is explicitly forbidden (SG-07).
# Production MUST set GHG_CORS_ORIGINS=https://dashboard.example.com
_CORS_ORIGINS_RAW: Final[str] = os.environ.get("GHG_CORS_ORIGINS", "")
_CORS_ORIGINS: Final[list[str]] = [
    o.strip() for o in _CORS_ORIGINS_RAW.split(",") if o.strip()
]


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
    # Middleware stack (applied in reverse — last added = outermost).
    # Desired wrap order, from innermost (closest to routes) to outermost:
    #   RateLimit → CorrelationId → ErrorHandler → SecurityHeaders → CORS
    # ErrorHandler must sit OUTSIDE CorrelationId so that exceptions raised
    # inside CorrelationIdMiddleware itself are still converted to RFC 7807
    # (instead of bubbling up as a generic 500). CORS stays outermost so that
    # every response — including error responses — carries CORS headers.
    # Allowed methods include DELETE/PUT so browsers can observe the explicit
    # 405 returned by the append-only emissions endpoints (CSRD audit trail).
    # ------------------------------------------------------------------
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(ErrorHandlerMiddleware)

    # SEC-P1-002: Security response headers (HSTS, CSP, X-Frame-Options, …)
    app.add_middleware(SecurityHeadersMiddleware)

    # SEC-P1-001: CORS — driven by GHG_CORS_ORIGINS env var; never wildcard.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-Id"],
    )

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
            the ``ctx`` mapping and raw input values inside ``input`` — both must
            be stripped before JSON serialisation (NFR-09 — no stack trace;
            NFR-08 — no PII in responses).  ``msg`` is also stripped because
            Pydantic frequently echoes the offending value inside the message
            (e.g. ``"String should match pattern '...': got 'user@example.com'"``)
            which would leak PII back to the caller.  ``loc`` and ``type`` are
            machine-actionable and safe to retain.
            """
            safe_keys = {"loc", "type"}
            return {k: v for k, v in err.items() if k in safe_keys}

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
    app.include_router(intensity.router)
    app.include_router(audit_trail.router)
    app.include_router(factor_catalog.router)
    app.include_router(dq_findings.router)
    app.include_router(go_certificates.router)
    app.include_router(reports.router)
    app.include_router(exports.router)

    return app


app = _create_app()

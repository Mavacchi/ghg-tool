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
    reconciliation,
    reports,
    sbti,
    users,
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


def _demo_mode_enabled() -> bool:
    """Return True iff GHG_DEMO_MODE is set to a truthy value."""
    return os.environ.get("GHG_DEMO_MODE", "").lower() in ("1", "true", "yes")


async def _seed_demo_data_if_empty() -> None:
    """Auto-seed the staging tables on first launch in demo mode.

    Guards (defense in depth, integrity-critical for a CSRD ledger):
      1. ``GHG_ENVIRONMENT`` must NOT be 'production' - a mis-set demo flag
         must never auto-seed a real production DB.
      2. ``GHG_DEMO_MODE`` must be truthy.
      3. ``raw.scope1_ingestions`` must be empty.

    Failures are logged but never abort startup.
    """
    if _ENVIRONMENT == "production":
        logger.info("demo_seed_skipped_production_environment")
        return
    if not _demo_mode_enabled():
        return
    try:
        # Local imports keep these heavy deps off the import-time graph
        # of the API process when demo mode is disabled.
        import asyncio  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        from ghg_tool.infrastructure.db.session import AsyncSessionFactory  # noqa: PLC0415

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM raw.scope1_ingestions")
            )
            count = result.scalar_one()
        if count and int(count) > 0:
            logger.info("demo_seed_skipped_already_populated", row_count=int(count))
            return

        logger.info("demo_seed_starting", reason="empty_raw_tables")

        def _run_seed() -> int:
            from scripts.seed_demo_data import main as seed_main  # noqa: PLC0415

            # No CLI args: defaults to data/raw/ and CERAMIC_TILE_CO tenant.
            return seed_main([])

        # The seed script uses sync psycopg, so run it in a worker thread
        # to avoid blocking the asyncio event loop.
        exit_code = await asyncio.to_thread(_run_seed)
        logger.info("demo_seed_finished", exit_code=exit_code)
    except (ImportError, FileNotFoundError, OSError, RuntimeError) as exc:
        logger.warning(
            "demo_seed_failed",
            error_type=type(exc).__name__,
            # Do NOT include the raw message: it may contain DSN / paths
            # we don't want in container logs.
        )


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
        demo_mode=_demo_mode_enabled(),
    )
    await _seed_demo_data_if_empty()
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
    # Wrap order, from innermost (closest to routes) to outermost:
    #   ErrorHandler → RateLimit → CorrelationId → SecurityHeaders → CORS
    # ErrorHandler is INNERMOST: BaseHTTPMiddleware runs the downstream
    # stack in an anyio child task, which means ContextVar mutations made
    # by CorrelationIdMiddleware do NOT propagate up to an outer
    # ErrorHandler. To keep error responses tagged with the right
    # correlation_id we let the inner ErrorHandler observe the ContextVar
    # set by the (outer) CorrelationIdMiddleware via the request-scoped
    # context that flows downward. CorrelationIdMiddleware's body is
    # narrow and itself try/except-guarded (see correlation_id.py), so
    # nothing inside it can escape uncaught.
    # CORS stays outermost so every response — including error responses
    # — carries CORS headers; allowed methods include DELETE/PUT so the
    # explicit 405 on append-only emission rows is observable by browsers.
    # ------------------------------------------------------------------
    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

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
            NFR-08 — no PII in responses).  ``msg`` is retained because it is
            part of the published OpenAPI validation-error contract, but is
            sanitised: error types known to echo the offending value back
            (e.g. ``string_pattern_mismatch``, ``value_error``) get a generic
            replacement message; all other types keep Pydantic's default.
            """
            out: dict = {}  # type: ignore[type-arg]
            err_type = err.get("type", "")
            pii_echo_types = {
                "string_pattern_mismatch",
                "value_error",
                "string_too_long",
                "string_too_short",
            }
            for k, v in err.items():
                if k in ("input", "url", "ctx"):
                    continue
                if k == "msg" and err_type in pii_echo_types:
                    out[k] = "Field failed validation"
                    continue
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
    app.include_router(intensity.router)
    app.include_router(audit_trail.router)
    app.include_router(factor_catalog.router)
    app.include_router(dq_findings.router)
    app.include_router(go_certificates.router)
    app.include_router(reports.router)
    app.include_router(exports.router)
    app.include_router(users.router)
    app.include_router(reconciliation.router)
    app.include_router(sbti.router)

    return app


app = _create_app()

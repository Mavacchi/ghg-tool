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
from ghg_tool.api.middleware.session_check import SessionCheckMiddleware
from ghg_tool.api.routers import (
    admin_tenants,
    analysis,
    audit_trail,
    auth,
    calc,
    chart_annotations,
    dq_findings,
    emissions,
    excel_import,
    exports,
    factor_catalog,
    go_certificates,
    health,
    intensity,
    kpis,
    reconciliation,
    reports,
    sbti,
    sessions,
    sites,
    totp,
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
    """Return True when demo mode is appropriate for the current environment.

    Rules (defense-in-depth):
    - ``ENV=production`` -> ALWAYS False, even if GHG_DEMO_MODE is set.
      Production must never run with hardcoded demo credentials.
    - ``ENV in ('development', 'demo')`` -> True automatically (no flag needed).
    - Any other environment (staging, test, …) -> only True when
      GHG_DEMO_MODE is explicitly set to a truthy value.
    """
    if _ENVIRONMENT == "production":
        return False
    if _ENVIRONMENT in ("development", "demo"):
        return True
    return os.environ.get("GHG_DEMO_MODE", "").lower() in ("1", "true", "yes")


async def _ensure_demo_user() -> None:
    """Insert a demo user into ``ref.users`` if one does not already exist.

    The demo user is created with:
      - username:  demo
      - password:  bcrypt("demo")
      - role:      editor (formerly data_steward, renamed in M24)
      - is_active: TRUE
      - tenant:    the launch tenant (GRESMALT, falling back to CERAMIC_TILE_CO)
      - email:     demo@demo.local (synthetic; never used for real mail)

    Credentials are logged at WARNING level so they appear in operational
    logs without being buried.  The password itself is never logged.

    Failures are caught and logged; they do NOT abort startup.
    """
    try:
        import asyncio  # noqa: PLC0415

        from sqlalchemy import text  # noqa: PLC0415

        from ghg_tool.infrastructure.db.session import AsyncSessionFactory  # noqa: PLC0415
        from ghg_tool.infrastructure.security.password import hash_password  # noqa: PLC0415

        def _hash() -> str:
            # Run bcrypt in a thread so it does not block the event loop.
            return hash_password("demo")

        async with AsyncSessionFactory() as session:
            # Check whether a "demo" user already exists (any tenant).
            exists_result = await session.execute(
                text("SELECT COUNT(*) FROM ref.users WHERE username = 'demo'")
            )
            if int(exists_result.scalar_one()) > 0:
                logger.info("demo_user_already_exists")
                return

            # Resolve tenant: prefer GRESMALT (post-M8 rebrand), fall back
            # to CERAMIC_TILE_CO (pre-M8 or test environments).
            tenant_result = await session.execute(
                text(
                    "SELECT id FROM ref.tenants "
                    "WHERE code IN ('GRESMALT', 'CERAMIC_TILE_CO') "
                    "ORDER BY CASE code WHEN 'GRESMALT' THEN 0 ELSE 1 END "
                    "LIMIT 1"
                )
            )
            tenant_row = tenant_result.fetchone()
            if tenant_row is None:
                logger.warning(
                    "demo_user_seed_skipped",
                    reason="no_launch_tenant_found",
                )
                return
            tenant_id = str(tenant_row[0])

            # Resolve role_id for editor (formerly data_steward, renamed in M24).
            role_result = await session.execute(
                text(
                    "SELECT id FROM ref.roles WHERE role_code = 'editor'"
                )
            )
            role_row = role_result.fetchone()
            if role_row is None:
                logger.warning(
                    "demo_user_seed_skipped",
                    reason="editor_role_not_found",
                )
                return
            role_id = str(role_row[0])

            password_hash = await asyncio.to_thread(_hash)

            await session.execute(
                text(
                    "INSERT INTO ref.users "
                    "  (tenant_id, username, email, password_hash, role_id, is_active) "
                    "VALUES "
                    "  (CAST(:tid AS uuid), :uname, :email, :phash, "
                    "   CAST(:rid AS uuid), TRUE)"
                ),
                {
                    "tid": tenant_id,
                    "uname": "demo",
                    "email": "demo@demo.local",
                    "phash": password_hash,
                    "rid": role_id,
                },
            )
            await session.commit()

        # Log credentials prominently so they surface in container logs.
        # The literal password string "demo" is intentional and documented.
        logger.warning(
            "demo_user_seeded",
            username="demo",
            password="demo (CHANGE BEFORE PRODUCTION)",  # noqa: S106 — demo cred, not real secret
            role="editor",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "demo_user_seed_failed",
            error_type=type(exc).__name__,
        )


async def _seed_admin_from_env_if_empty() -> None:
    """Insert an admin user from env vars if ref.users is empty.

    Reads ``GHG_BOOTSTRAP_ADMIN_USERNAME``, ``GHG_BOOTSTRAP_ADMIN_EMAIL``,
    and ``GHG_BOOTSTRAP_ADMIN_PASSWORD_HASH`` (bcrypt hash — never plaintext).
    All three must be set for the bootstrap to run.

    Guards (idempotency + safety):
      1. All three env vars must be non-empty.
      2. Skip when ``GHG_ENVIRONMENT == 'test'`` — bootstrap must not pollute
         the test database.
      3. Skip when ``ref.users`` already has at least one row (idempotent:
         re-running after a partial rebuild is safe).

    This function is intentionally separate from ``_seed_demo_data_if_empty``
    so that neither depends on the other and both can fail independently
    without aborting startup.

    Args:  None (reads from os.environ and the DB).

    Returns:  None.  All failures are logged and swallowed so the API stays
        reachable.
    """
    if _ENVIRONMENT == "test":
        return

    username = os.environ.get("GHG_BOOTSTRAP_ADMIN_USERNAME", "").strip()
    email = os.environ.get("GHG_BOOTSTRAP_ADMIN_EMAIL", "").strip()
    password_hash = os.environ.get("GHG_BOOTSTRAP_ADMIN_PASSWORD_HASH", "").strip()

    if not (username and email and password_hash):
        # Env vars not configured — normal non-bootstrap deployment; skip silently.
        return

    try:
        from sqlalchemy import text  # noqa: PLC0415

        from ghg_tool.infrastructure.db.session import AsyncSessionFactory  # noqa: PLC0415

        async with AsyncSessionFactory() as session:
            # Idempotency guard: skip if any user already exists.
            count_result = await session.execute(
                text("SELECT COUNT(*) FROM ref.users")
            )
            user_count = int(count_result.scalar_one())
            if user_count > 0:
                logger.info(
                    "bootstrap_admin_skipped",
                    reason="users_table_not_empty",
                    user_count=user_count,
                )
                return

            # Resolve tenant (GRESMALT preferred, CERAMIC_TILE_CO fallback).
            tenant_result = await session.execute(
                text(
                    "SELECT id FROM ref.tenants "
                    "WHERE code IN ('GRESMALT', 'CERAMIC_TILE_CO') "
                    "ORDER BY CASE code WHEN 'GRESMALT' THEN 0 ELSE 1 END "
                    "LIMIT 1"
                )
            )
            tenant_row = tenant_result.fetchone()
            if tenant_row is None:
                logger.warning(
                    "bootstrap_admin_skipped",
                    reason="no_launch_tenant_found",
                )
                return
            tenant_id = str(tenant_row[0])

            # Resolve admin role.
            role_result = await session.execute(
                text("SELECT id FROM ref.roles WHERE role_code = 'admin'")
            )
            role_row = role_result.fetchone()
            if role_row is None:
                logger.warning(
                    "bootstrap_admin_skipped",
                    reason="admin_role_not_found",
                )
                return
            role_id = str(role_row[0])

            await session.execute(
                text(
                    "INSERT INTO ref.users "
                    "  (tenant_id, username, email, password_hash, role_id, is_active) "
                    "VALUES "
                    "  (CAST(:tid AS uuid), :uname, :email, :phash, "
                    "   CAST(:rid AS uuid), TRUE)"
                ),
                {
                    "tid": tenant_id,
                    "uname": username,
                    "email": email,
                    "phash": password_hash,
                    "rid": role_id,
                },
            )
            await session.commit()

        # Log at WARNING so it surfaces in container logs.
        # Do NOT log email or hash.
        logger.warning(
            "bootstrap_admin_seeded_from_env",
            username=username,
        )

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "bootstrap_admin_seed_failed",
            error_type=type(exc).__name__,
        )
        # Do NOT re-raise — the API must remain reachable even if bootstrap fails.


async def _seed_demo_data_if_empty() -> None:
    """Auto-seed the staging tables on first launch in demo mode.

    Guards (defense in depth, integrity-critical for a CSRD ledger):
      1. ``GHG_ENVIRONMENT`` must NOT be 'production' — a mis-set demo flag
         must never auto-seed a real production DB.
      2. ``_demo_mode_enabled()`` must return True.
      3. Real production data must be absent: if ``ref.tenants`` contains more
         than the M0 seed row the DB is considered live and seeding is skipped.

    Seed-CSV handling: if the CSVs are missing from the deployed image the
    function logs a clear warning and skips seeding without crashing.

    Failures are logged but never abort startup — the API remains reachable
    even when seeding partially fails.
    """
    if _ENVIRONMENT == "production":
        logger.info("demo_seed_skipped_production_environment")
        return
    if not _demo_mode_enabled():
        return

    # Emit a visible warning so operators know demo mode is active.
    logger.warning(
        "demo_mode_active",
        env=_ENVIRONMENT,
        note="hardcoded demo credentials present — NEVER run in production",
    )

    try:
        # Local imports keep these heavy deps off the import-time graph
        # of the API process when demo mode is disabled.
        import asyncio  # noqa: PLC0415
        from pathlib import Path as _Path  # noqa: PLC0415

        from sqlalchemy import text  # noqa: PLC0415

        from ghg_tool.infrastructure.db.session import AsyncSessionFactory  # noqa: PLC0415

        # ------------------------------------------------------------------
        # Guard 1: skip if real data is present (more than the M0 tenant row).
        # We check raw.scope1_ingestions row count as the canonical signal
        # that real activity data has been loaded.
        # ------------------------------------------------------------------
        async with AsyncSessionFactory() as session:
            tenant_result = await session.execute(
                text("SELECT COUNT(*) FROM ref.tenants")
            )
            tenant_count = int(tenant_result.scalar_one())

            s1_result = await session.execute(
                text("SELECT COUNT(*) FROM raw.scope1_ingestions")
            )
            s1_count = int(s1_result.scalar_one())

        if tenant_count > 1:
            logger.info(
                "demo_seed_skipped_real_data_present",
                tenant_count=tenant_count,
            )
            await _ensure_demo_user()
            return

        if s1_count > 0:
            logger.info(
                "demo_seed_skipped_already_populated",
                row_count=s1_count,
            )
            await _ensure_demo_user()
            return

        # ------------------------------------------------------------------
        # Guard 2: verify seed CSVs exist before trying to run the pipeline.
        # Missing CSVs in a slim image should produce a clear warning, not a
        # hard crash.
        # ------------------------------------------------------------------
        _data_dir = _Path(__file__).resolve().parent.parent.parent.parent / "data" / "raw"
        _required_csvs = [
            _data_dir / "scope1_combustione.csv",
            _data_dir / "scope2_elettricita.csv",
            _data_dir / "scope3_categorie.csv",
        ]
        _missing = [str(p) for p in _required_csvs if not p.exists()]
        if _missing:
            logger.warning(
                "demo_seed_skipped_missing_csvs",
                missing=_missing,
                note="deploy data/raw/ CSVs to enable auto-seeding",
            )
            await _ensure_demo_user()
            return

        logger.info("demo_seed_starting", reason="empty_raw_tables")

        def _run_seed() -> int:
            from scripts.seed_demo_data import main as seed_main  # noqa: PLC0415

            # No CLI args: defaults to data/raw/ and CERAMIC_TILE_CO tenant.
            return seed_main([])

        # The seed script uses sync psycopg, so run it in a worker thread
        # to avoid blocking the asyncio event loop.
        exit_code = await asyncio.to_thread(_run_seed)

        # Log per-scope row counts after a successful seed.
        async with AsyncSessionFactory() as session:
            counts: dict[str, int] = {}
            for tbl in ("scope1_ingestions", "scope2_ingestions", "scope3_ingestions"):
                res = await session.execute(
                    text(f"SELECT COUNT(*) FROM raw.{tbl}")  # noqa: S608
                )
                counts[tbl] = int(res.scalar_one())

        logger.info(
            "demo_seed_finished",
            exit_code=exit_code,
            scope1_rows=counts.get("scope1_ingestions", 0),
            scope2_rows=counts.get("scope2_ingestions", 0),
            scope3_rows=counts.get("scope3_ingestions", 0),
        )
    except (ImportError, FileNotFoundError, OSError, RuntimeError, Exception) as exc:  # noqa: BLE001
        logger.warning(
            "demo_seed_failed",
            error_type=type(exc).__name__,
            # Do NOT include the raw message: it may contain DSN / paths
            # we don't want in container logs.
        )
        # Do NOT re-raise — the API must remain reachable even if seeding fails.

    # Always attempt to create the demo user, even if CSV seeding failed.
    await _ensure_demo_user()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan context — startup and shutdown hooks.

    Starts the optional APScheduler calc scheduler when
    ``GHG_CALC_SCHEDULE_CRON`` is set (see
    ``infrastructure.scheduling.calc_scheduler``).  The scheduler is shut
    down cleanly on exit regardless of whether startup completed.

    Args:
        app: The FastAPI application instance.

    Yields:
        Control to the request-handling loop.
    """
    import datetime as _dt  # noqa: PLC0415

    from ghg_tool.infrastructure.scheduling.calc_scheduler import (  # noqa: PLC0415
        start_scheduler,
    )

    logger.info(
        "GHG API starting",
        version=_VERSION,
        environment=_ENVIRONMENT,
        demo_mode=_demo_mode_enabled(),
    )
    await _seed_admin_from_env_if_empty()
    await _seed_demo_data_if_empty()

    current_anno = _dt.datetime.now(_dt.UTC).year
    _scheduler = start_scheduler(anno=current_anno)

    try:
        yield
    finally:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            logger.info("calc_scheduler_stopped")
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
    # SessionCheckMiddleware runs inside RateLimitMiddleware so rate-limited
    # requests are rejected before a DB lookup is attempted.
    app.add_middleware(SessionCheckMiddleware)
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
    app.include_router(totp.router)
    app.include_router(sessions.router)
    app.include_router(calc.router)
    app.include_router(emissions.router)
    app.include_router(excel_import.router)
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
    app.include_router(chart_annotations.router)
    app.include_router(sites.router)
    # Wave4 Task C: Scope 3 hot-spot analysis endpoint
    app.include_router(analysis.router)
    # Wave4 Task 4 (cluster E): admin tenant management
    app.include_router(admin_tenants.router)

    return app


app = _create_app()

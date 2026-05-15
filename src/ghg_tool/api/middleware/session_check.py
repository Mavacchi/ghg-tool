"""Session revocation check middleware (Sessions v2 -- M16).

On every authenticated request this middleware:
1. Decodes the Authorization: Bearer header WITH SIGNATURE VERIFICATION
   (S-012/S-024 fix -- previously used unverified decode).
   Trade-off note: this causes a duplicate JWT decode (the auth dependency
   also decodes).  The cost is acceptable: a single HS256/RS256 decode is
   microseconds, while the DB lookup dominates latency.  The middleware is
   the FIRST line of defence; get_current_user is the second.
2. Looks up auth.sessions WHERE jti = :jti.
3. If the row is missing AND the path is not in _NO_SESSION_PATHS -> 401
   session_not_found (fail-closed after BUG-01 fix -- every issued token
   now has a session row).
4. If revoked_at IS NOT NULL -> 401 session_revoked.
5. Otherwise fires off a best-effort asyncio.create_task last_seen_at update
   (BUG-12: replaced asyncio.ensure_future; task has an exception callback).

BUG-21: removed dead `import time`.
BUG-22: correlation_id is bound on every log line.
BUG-12: asyncio.ensure_future replaced with asyncio.create_task + done callback.
BUG-14 (last_seen): UPDATE has AND revoked_at IS NULL guard (BUG-18).
S-012/S-022/S-024: DB errors return 503 (fail-closed); middleware no longer
    passes the request through on error.

Paths excluded from session-row requirement:
  /api/v1/auth/login, /api/v1/auth/totp/challenge, /api/v1/auth/refresh,
  /api/v1/auth/logout, /healthz, /readyz, /openapi.json, /docs, /redoc
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import structlog
from fastapi import Request, Response
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ghg_tool.infrastructure.db.session import AsyncSessionFactory
from ghg_tool.infrastructure.security import jwt as jwt_module

logger = structlog.get_logger(__name__)

_EXCLUDED_PATHS = frozenset({"/healthz", "/readyz"})

# Paths that issue tokens (or are unauthenticated bootstrap endpoints) and
# therefore do NOT require a pre-existing session row.
_NO_SESSION_PATHS = frozenset({
    "/api/v1/auth/login",
    "/api/v1/auth/totp/challenge",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/openapi.json",
    "/docs",
    "/redoc",
})


class SessionCheckMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that validates session liveness on each request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Coroutine[Any, Any, Response]],
    ) -> Response:
        """Check session revocation before forwarding the request."""
        from ghg_tool.api.middleware.correlation_id import get_correlation_id  # noqa: PLC0415

        correlation_id = get_correlation_id()
        path = request.url.path

        if path in _EXCLUDED_PATHS or path in _NO_SESSION_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return await call_next(request)

        # S-012/S-024: decode WITH signature verification, not unverified peek.
        # Duplicate decode: the auth dependency will also decode.  Acceptable
        # cost -- the DB lookup dominates latency.  This is the first line of
        # defence; get_current_user is the second.
        try:
            token = auth_header.removeprefix("Bearer ")
            claims = jwt_module.decode_token(token)
            jti: str = str(claims.get("jti", "")) or ""
        except Exception:  # noqa: BLE001
            # Invalid / expired token -- let the auth dependency handle the 401.
            return await call_next(request)

        if not jti:
            return await call_next(request)

        try:
            async with AsyncSessionFactory() as db:
                result = await db.execute(
                    text(
                        "SELECT id, revoked_at FROM auth.sessions "
                        "WHERE jti = :jti LIMIT 1"
                    ),
                    {"jti": jti},
                )
                row = result.fetchone()

        except Exception as exc:  # noqa: BLE001
            # S-012/S-022: fail-CLOSED on DB error; do NOT pass the request through.
            logger.bind(correlation_id=correlation_id).error(
                "session_check_middleware_db_error",
                error_class=type(exc).__name__,
            )
            return JSONResponse(
                status_code=503,
                content={
                    "type": "about:blank",
                    "title": "Service Unavailable",
                    "status": 503,
                    "detail": "service_unavailable",
                    "correlation_id": correlation_id,
                },
            )

        if row is None:
            # BUG-19 / BUG-01: with session rows created at issuance, a missing
            # row means a forged or pre-fix token -- reject fail-closed.
            logger.bind(correlation_id=correlation_id).warning(
                "session_not_found_request_blocked",
                jti_prefix=jti[:8],
            )
            return JSONResponse(
                status_code=401,
                content={
                    "type": "about:blank",
                    "title": "Unauthorized",
                    "status": 401,
                    "detail": "session_not_found",
                    "correlation_id": correlation_id,
                },
            )

        if row.revoked_at is not None:
            logger.bind(correlation_id=correlation_id).warning(
                "session_revoked_request_blocked",
                jti_prefix=jti[:8],
            )
            return JSONResponse(
                status_code=401,
                content={
                    "type": "about:blank",
                    "title": "Unauthorized",
                    "status": 401,
                    "detail": "session_revoked",
                    "correlation_id": correlation_id,
                },
            )

        # BUG-12: best-effort last_seen_at update using create_task + done callback.
        # BUG-18: UPDATE has AND revoked_at IS NULL guard to avoid bumping
        #         last_seen_at on a session that was just revoked.
        _session_id = str(row.id)
        task = asyncio.create_task(_update_last_seen(_session_id, correlation_id))
        task.add_done_callback(
            lambda t: t.exception() and logger.warning(
                "last_seen_update_failed",
                error=str(t.exception()),
                correlation_id=correlation_id,
            )
        )

        return await call_next(request)


async def _update_last_seen(session_id: str, correlation_id: str) -> None:
    """Update last_seen_at for the given session (best-effort, never blocks response).

    BUG-18: only updates when revoked_at IS NULL to avoid misleading forensics.
    """
    try:
        async with AsyncSessionFactory() as db2:
            await db2.execute(
                text(
                    "UPDATE auth.sessions SET last_seen_at = now() "
                    "WHERE id = CAST(:sid AS uuid) "
                    "  AND revoked_at IS NULL"
                ),
                {"sid": session_id},
            )
            await db2.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "last_seen_update_failed",
            error=str(exc),
            correlation_id=correlation_id,
        )

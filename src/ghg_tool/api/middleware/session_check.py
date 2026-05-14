"""Session revocation check middleware (Sessions v2 -- M16).

On every authenticated request this middleware:
1. Peeks at the Authorization: Bearer header (without re-validating the full JWT
   so there is no double-verification cost).
2. Looks up auth.sessions WHERE jti = :jti.
3. If revoked_at IS NOT NULL -> 401 session_revoked.
4. Otherwise fires off a best-effort UPDATE last_seen_at = now() (background,
   never blocks the response).

Unauthenticated requests (no Bearer header) pass through without a DB lookup.
Paths excluded: /healthz and /readyz (infra probes, no session row expected).
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable, Coroutine
from typing import Any

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = structlog.get_logger(__name__)

_EXCLUDED_PATHS = frozenset({"/healthz", "/readyz"})

# Paths that issue tokens but do not yet have a session row (e.g. /login itself
# creates the row AFTER the middleware runs, /totp/challenge also creates one).
_NO_SESSION_PATHS = frozenset({
    "/api/v1/auth/login",
    "/api/v1/auth/totp/challenge",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
})


def _extract_jti(authorization: str) -> str | None:
    """Attempt to extract the jti claim from a raw Bearer JWT without verifying.

    Returns None on any parse failure.
    """
    try:
        parts = authorization.removeprefix("Bearer ").split(".")
        if len(parts) < 2:
            return None
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return str(payload.get("jti", "")) or None
    except Exception:  # noqa: BLE001 -- best effort peek
        return None


class SessionCheckMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that validates session liveness on each request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Coroutine[Any, Any, Response]],
    ) -> Response:
        """Check session revocation before forwarding the request."""
        path = request.url.path
        if path in _EXCLUDED_PATHS or path in _NO_SESSION_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return await call_next(request)

        jti = _extract_jti(auth_header)
        if not jti:
            return await call_next(request)

        # Lazy import to avoid circular deps at module load.
        try:
            from sqlalchemy import text  # noqa: PLC0415

            from ghg_tool.infrastructure.db.session import AsyncSessionFactory  # noqa: PLC0415

            async with AsyncSessionFactory() as db:
                result = await db.execute(
                    text(
                        "SELECT id, revoked_at FROM auth.sessions "
                        "WHERE jti = :jti LIMIT 1"
                    ),
                    {"jti": jti},
                )
                row = result.fetchone()

            if row is not None and row.revoked_at is not None:
                logger.warning(
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
                    },
                )

            # Best-effort last_seen_at update -- fire and forget.
            if row is not None:
                import asyncio  # noqa: PLC0415

                async def _update_last_seen(session_id: str) -> None:
                    try:
                        async with AsyncSessionFactory() as db2:
                            await db2.execute(
                                text(
                                    "UPDATE auth.sessions SET last_seen_at = now() "
                                    "WHERE id = CAST(:sid AS uuid)"
                                ),
                                {"sid": str(session_id)},
                            )
                            await db2.commit()
                    except Exception:  # noqa: BLE001
                        pass

                asyncio.ensure_future(_update_last_seen(str(row.id)))

        except Exception as exc:  # noqa: BLE001 -- middleware must not crash the request
            logger.warning(
                "session_check_middleware_error",
                error_class=type(exc).__name__,
            )

        return await call_next(request)

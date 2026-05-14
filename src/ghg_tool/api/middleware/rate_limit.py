"""In-process rate-limit middleware — SG-10, NFR-11.

Limits authenticated users to 100 requests per minute using a simple
token-bucket / sliding-window approach backed by an in-memory dict.
A Redis-backed implementation (via slowapi) is the production upgrade path;
the interface is identical.

Health / readiness endpoints are exempt from rate limiting.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ghg_tool.api.middleware.error_handler import build_problem_response

_RATE_LIMIT_REQUESTS: int = 100
_RATE_LIMIT_WINDOW_S: int = 60  # 1 minute sliding window

# SEC-P1-003: Stricter rate limit for /auth/login — 5 attempts per minute per IP
_LOGIN_RATE_LIMIT_REQUESTS: int = 5
_LOGIN_RATE_LIMIT_WINDOW_S: int = 60

# Per-route bucket for /factor-catalog/.../publish.
# Factor publication is a low-frequency, high-impact operation (the row
# becomes immutable after the call). 10/min per user is generous for any
# legitimate workflow and gives SIEM a clear signal on burst attempts.
_PUBLISH_RATE_LIMIT_REQUESTS: int = 10
_PUBLISH_RATE_LIMIT_WINDOW_S: int = 60

# Exempt paths (no auth, no rate limiting)
_EXEMPT_PREFIXES: frozenset[str] = frozenset({"/healthz", "/readyz", "/openapi", "/docs"})


class _SlidingWindowCounter:
    """Thread-safe per-key sliding window request counter.

    Uses a ``deque`` of timestamps to track requests within the window.
    """

    def __init__(self, window_s: int, limit: int) -> None:
        """Initialise with window duration and request limit.

        Args:
            window_s: Window size in seconds.
            limit: Maximum allowed requests within the window.
        """
        self._window = window_s
        self._limit = limit
        self._buckets: dict[str, deque[float]] = {}
        self._lock = Lock()

    def is_allowed(self, key: str) -> bool:
        """Check and record a request; return False if the limit is exceeded.

        Args:
            key: Unique identifier for the caller (e.g. user_id or IP).

        Returns:
            True if the request is within the rate limit; False otherwise.
        """
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            # Evict timestamps outside the sliding window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._limit:
                return False
            bucket.append(now)
            return True

    def reset(self) -> None:
        """Clear all rate-limit counters.  Intended for use in test fixtures only."""
        with self._lock:
            self._buckets.clear()


_counter = _SlidingWindowCounter(
    window_s=_RATE_LIMIT_WINDOW_S,
    limit=_RATE_LIMIT_REQUESTS,
)

# SEC-P1-003: separate stricter counter for the login endpoint
login_limiter = _SlidingWindowCounter(
    window_s=_LOGIN_RATE_LIMIT_WINDOW_S,
    limit=_LOGIN_RATE_LIMIT_REQUESTS,
)

# Per-route counter for factor publication (POST /factor-catalog/.../publish).
publish_limiter = _SlidingWindowCounter(
    window_s=_PUBLISH_RATE_LIMIT_WINDOW_S,
    limit=_PUBLISH_RATE_LIMIT_REQUESTS,
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate-limit middleware (100 req/min per authenticated user).

    The caller key is derived (in priority order) from:
    1. The ``sub`` claim in the decoded JWT (set as ``request.state.user_sub``
       by the auth dependency — available for routes that have passed auth).
    2. The client IP address (fallback for unauthenticated requests that are
       not on the exempt list).

    Exempt paths (``/healthz``, ``/readyz``, ``/docs``, ``/openapi``) are
    always allowed through.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Apply rate limiting before passing the request downstream.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            The response, or a 429 Too Many Requests problem response.
        """
        path = request.url.path
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        rate_key = _extract_rate_key(request)
        if not _counter.is_allowed(rate_key):
            from ghg_tool.api.middleware.correlation_id import get_correlation_id
            return build_problem_response(
                status=429,
                title="Too Many Requests",
                detail=(
                    f"Rate limit exceeded: {_RATE_LIMIT_REQUESTS} requests "
                    f"per {_RATE_LIMIT_WINDOW_S} seconds."
                ),
                correlation_id=get_correlation_id(),
            )
        return await call_next(request)


def _extract_rate_key(request: Request) -> str:
    """Extract a rate-limit key from the request state or Bearer JWT sub.

    Priority order (BUG-08 fix):
    1. ``request.state.user_sub`` (set by auth dependency -- only available
       after auth middleware has run, which is AFTER rate-limit middleware
       for most routes; therefore this is usually None at middleware time).
    2. Bearer JWT ``sub`` claim decoded WITHOUT signature verification.
       This is safe: the sub is used only as a rate-limit routing key, not
       for authorisation.  The auth dependency performs the authoritative
       signature check later.
    3. Fallback to client IP for requests without a Bearer token.

    Args:
        request: The HTTP request.

    Returns:
        A string key uniquely identifying the caller for rate-limiting purposes.
    """
    # Priority 1: already decoded by auth dependency (rare at middleware time)
    user_sub: str | None = getattr(request.state, "user_sub", None)
    if user_sub:
        return f"user:{user_sub}"

    # Priority 2: extract sub from Bearer JWT without signature verification.
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ")
        try:
            from ghg_tool.infrastructure.security import jwt as jwt_module  # noqa: PLC0415
            unverified = jwt_module.get_unverified_claims(token)
            sub: str = str(unverified.get("sub", ""))
            if sub:
                return f"user:{sub}"
        except Exception:  # noqa: BLE001 -- best effort; fall through to IP
            pass

    # Priority 3: fallback to client IP
    client_host = request.client.host if request.client else "unknown"
    return f"ip:{client_host}"

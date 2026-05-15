"""Rate-limit middleware -- SG-10, NFR-11, SEC-ADV-008.

Limits authenticated users to 100 requests per minute using a sliding-window
counter.  Storage:

- **Production**: a shared Redis instance (URL from ``REDIS_URL``), via the
  ``limits`` library (the same backend slowapi uses internally).  Counters
  are coordinated across replicas so a single user's burst against any
  replica is honoured against the same budget on every other replica
  (SEC-ADV-008).
- **Fallback** (single-process dev runs, unit tests): an in-process
  sliding-window counter.  Selected automatically when Redis is not
  available, with a WARNING emitted at startup so operators cannot
  accidentally rely on it in production.

Public API kept unchanged for back-compat with router-level callers:
``_counter.is_allowed(key)``, ``_counter.reset()``, ``login_limiter``,
``publish_limiter``.  The implementation behind the API is selected once
at module import time based on ``redis_client.using_in_memory_fallback()``.

Health / readiness endpoints are exempt from rate limiting.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import TYPE_CHECKING

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ghg_tool.api.middleware.error_handler import build_problem_response

if TYPE_CHECKING:  # pragma: no cover
    pass

_log = structlog.get_logger(__name__)

_RATE_LIMIT_REQUESTS: int = 100
_RATE_LIMIT_WINDOW_S: int = 60  # 1 minute sliding window

# SEC-P1-003: Stricter rate limit for /auth/login -- 5 attempts per minute per IP
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


# ---------------------------------------------------------------------------
# In-memory implementation -- the legacy ``_SlidingWindowCounter``.
# Kept as the fallback backend so tests can run without Redis.
# ---------------------------------------------------------------------------


class _InMemorySlidingWindow:
    """Thread-safe per-key sliding-window request counter.

    Uses a ``deque`` of timestamps to track requests within the window.
    """

    def __init__(self, window_s: int, limit: int) -> None:
        self._window = window_s
        self._limit = limit
        self._buckets: dict[str, deque[float]] = {}
        self._lock = Lock()

    def is_allowed(self, key: str) -> bool:
        """Check and record a request; return False if the limit is exceeded."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
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


# ---------------------------------------------------------------------------
# Redis-backed implementation -- SEC-ADV-008.
# Uses the ``limits`` library (a slowapi dependency) which natively supports
# a Redis storage backend and a moving-window rate-limit strategy.
# ---------------------------------------------------------------------------


class _RedisSlidingWindow:
    """Moving-window rate limiter backed by a shared Redis instance.

    Wraps ``limits.strategies.MovingWindowRateLimiter`` so the public
    ``is_allowed/reset`` shape matches the in-memory counter exactly.
    Counters are namespaced with ``namespace`` so the three buckets
    (general / login / publish) cannot collide on a shared Redis.
    """

    def __init__(
        self,
        *,
        window_s: int,
        limit: int,
        namespace: str,
        storage_uri: str,
    ) -> None:
        # Local imports keep this expensive dependency out of the hot path
        # when the in-memory fallback is selected.
        from limits import RateLimitItemPerSecond  # noqa: PLC0415
        from limits.storage import storage_from_string  # noqa: PLC0415
        from limits.strategies import MovingWindowRateLimiter  # noqa: PLC0415

        self._namespace = namespace
        self._storage = storage_from_string(storage_uri)
        self._strategy = MovingWindowRateLimiter(self._storage)
        # MovingWindow counts per second, so we model "N per W seconds" as
        # ``RateLimitItemPerSecond(N, multiples=W)``.
        self._item = RateLimitItemPerSecond(limit, multiples=window_s)

    def _key(self, raw: str) -> str:
        return f"{self._namespace}:{raw}"

    def is_allowed(self, key: str) -> bool:
        """Atomically test+increment the bucket for ``key``.

        Returns False once the moving-window total reaches the limit.
        """
        # ``hit`` returns True when the request is *allowed* (consumed a slot).
        return bool(self._strategy.hit(self._item, self._key(key)))

    def reset(self) -> None:
        """Drop all per-key state -- test-only helper.

        For Redis: ``storage.reset()`` clears every key in the namespace.
        """
        # Some limits storage backends do not implement reset (e.g. the
        # read-only cluster client).  Best effort: suppress so test
        # fixtures can call reset() unconditionally.
        import contextlib  # noqa: PLC0415 -- local to keep top-level imports lean

        with contextlib.suppress(NotImplementedError):
            self._storage.reset()


# ---------------------------------------------------------------------------
# Factory: pick the implementation once at import time.
# ---------------------------------------------------------------------------


def _build_counter(*, window_s: int, limit: int, namespace: str) -> object:
    """Construct a per-bucket counter, preferring Redis when available."""
    from ghg_tool.infrastructure import redis_client  # noqa: PLC0415

    storage_uri = redis_client.get_storage_uri()
    if redis_client.using_in_memory_fallback():
        # ``get_storage_uri`` returns ``"memory://"`` in this case; we use
        # our own in-memory deque implementation instead of the limits
        # in-memory backend so the behaviour exactly matches the legacy
        # pre-SEC-ADV-008 counter (existing tests pin the exact semantics).
        _log.warning(
            "rate_limiter_in_memory_fallback",
            namespace=namespace,
            advisory=(
                "Redis unavailable; rate limiter falls back to per-process "
                "in-memory storage.  Counters are NOT coordinated across "
                "replicas; do not run multi-instance deployments in this mode."
            ),
        )
        return _InMemorySlidingWindow(window_s=window_s, limit=limit)
    _log.info(
        "rate_limiter_redis_backed",
        namespace=namespace,
        storage_uri=storage_uri,
    )
    return _RedisSlidingWindow(
        window_s=window_s,
        limit=limit,
        namespace=namespace,
        storage_uri=storage_uri,
    )


# SEC-ADV-008: three independent buckets, each backed by the active store.
_counter = _build_counter(
    window_s=_RATE_LIMIT_WINDOW_S,
    limit=_RATE_LIMIT_REQUESTS,
    namespace="ghg:rl:general",
)

# SEC-P1-003: separate stricter counter for the login endpoint.
login_limiter = _build_counter(
    window_s=_LOGIN_RATE_LIMIT_WINDOW_S,
    limit=_LOGIN_RATE_LIMIT_REQUESTS,
    namespace="ghg:rl:login",
)

# Per-route counter for factor publication (POST /factor-catalog/.../publish).
publish_limiter = _build_counter(
    window_s=_PUBLISH_RATE_LIMIT_WINDOW_S,
    limit=_PUBLISH_RATE_LIMIT_REQUESTS,
    namespace="ghg:rl:publish",
)


# ---------------------------------------------------------------------------
# Backwards-compatible alias.
# ---------------------------------------------------------------------------
# Existing tests import ``_SlidingWindowCounter`` directly.  Keep the symbol
# pointing at the in-memory implementation (the class historically guaranteed
# in-memory semantics for test fixtures).
_SlidingWindowCounter = _InMemorySlidingWindow


# ---------------------------------------------------------------------------
# Middleware -- unchanged behaviour, only ``_counter`` typing widened.
# ---------------------------------------------------------------------------


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate-limit middleware (100 req/min per authenticated user).

    The caller key is derived (in priority order) from:
    1. The ``sub`` claim in the decoded JWT (set as ``request.state.user_sub``
       by the auth dependency -- available for routes that have passed auth).
    2. The client IP address (fallback for unauthenticated requests that are
       not on the exempt list).

    Exempt paths (``/healthz``, ``/readyz``, ``/docs``, ``/openapi``) are
    always allowed through.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Apply rate limiting before passing the request downstream."""
        path = request.url.path
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        rate_key = _extract_rate_key(request)
        if not _counter.is_allowed(rate_key):  # type: ignore[attr-defined]
            from ghg_tool.api.middleware.correlation_id import (  # noqa: PLC0415
                get_correlation_id,
            )
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
    """
    user_sub: str | None = getattr(request.state, "user_sub", None)
    if user_sub:
        return f"user:{user_sub}"

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

    client_host = request.client.host if request.client else "unknown"
    return f"ip:{client_host}"

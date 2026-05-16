"""Redis client singleton -- SEC-P1-007 + SEC-ADV-008 shared dependency.

Two production hardening features need Redis:

- **SEC-P1-007**: JWT token blacklist (revocation on logout, refresh
  rotation, compromise containment).
- **SEC-ADV-008**: distributed rate limiter (slowapi storage backend) so
  request budgets are coordinated across replicas.

Both should use the *same* Redis instance to keep the deployment surface
small.  This module owns the lazy connection-pool singleton and the
in-memory fallback used in dev/test where a real Redis is not running.

Design
------
- ``get_redis_client()`` returns a ``RedisLike`` object: either a real
  ``redis.Redis`` instance (with connection pooling) or an in-memory
  ``_InMemoryRedis`` adapter.  Both expose the small subset of the
  Redis API that the token blacklist uses: ``setex``, ``exists``,
  ``delete``, ``ping``.
- Decision is made on the first ``get_redis_client()`` call.  A
  ``WARNING`` is logged whenever the fallback is selected so operators
  cannot accidentally run production on the in-memory shim.
- ``get_storage_uri()`` returns either the configured ``REDIS_URL`` (so
  slowapi can configure its own pool) or ``"memory://"`` for the
  fallback.  This is what TASK-C wires into ``slowapi.Limiter``.

The fallback is **not** safe for multi-process or multi-instance
deployments -- entries live in process memory and TTLs are honoured by
a single background sweep on each call.  It exists so unit tests can
exercise the full code path without standing up a real Redis.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Protocol, runtime_checkable

import structlog

_log = structlog.get_logger(__name__)

DEFAULT_REDIS_URL: str = "redis://localhost:6379/0"


def _resolve_redis_url() -> str:
    """Return the Redis URL from env (``REDIS_URL``) or the default."""
    return os.environ.get("REDIS_URL", DEFAULT_REDIS_URL).strip() or DEFAULT_REDIS_URL


def _force_in_memory() -> bool:
    """Return True when the in-memory fallback is explicitly requested.

    Set ``GHG_REDIS_DISABLED=1`` in unit tests so they never reach a
    real Redis even when ``REDIS_URL`` is configured in the shell env.
    """
    return os.environ.get("GHG_REDIS_DISABLED", "").strip() in {"1", "true", "yes"}


# ---------------------------------------------------------------------------
# RedisLike protocol -- the *only* subset of the Redis API the rest of the
# codebase is allowed to use.  Keeping this small lets the in-memory shim
# stay correct.
# ---------------------------------------------------------------------------


@runtime_checkable
class RedisLike(Protocol):
    """Minimal Redis surface used by the token-blacklist + rate limiter."""

    def setex(self, name: str, time: int, value: str | bytes) -> bool: ...
    def exists(self, name: str) -> int: ...
    def delete(self, *names: str) -> int: ...
    def ping(self) -> bool: ...


# ---------------------------------------------------------------------------
# In-memory fallback
# ---------------------------------------------------------------------------


class _InMemoryRedis:
    """Thread-safe, TTL-aware in-memory shim.

    *Not* a drop-in replacement for Redis -- only implements the
    operations the application actually uses.  Entries expire at the
    deadline timestamp; expired entries are pruned on every access so
    ``exists()`` never returns a stale True.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[str | bytes, float]] = {}
        self._lock = threading.Lock()

    def _prune(self) -> None:
        now = _now_monotonic()
        # Iterate over a snapshot of the keys so we can delete safely.
        dead = [k for k, (_, exp) in self._store.items() if exp <= now]
        for k in dead:
            self._store.pop(k, None)

    def setex(self, name: str, time: int, value: str | bytes) -> bool:
        """Set ``name`` -> ``value`` with TTL ``time`` seconds.

        Mirrors ``redis.Redis.setex``.  Returns True on success.
        """
        if time <= 0:
            # Redis rejects non-positive TTLs; mirror the behaviour rather
            # than silently storing an entry that never expires.
            raise ValueError("setex TTL must be > 0")
        deadline = _now_monotonic() + float(time)
        with self._lock:
            self._prune()
            self._store[name] = (value, deadline)
        return True

    def exists(self, name: str) -> int:
        """Return 1 if ``name`` exists and is unexpired, else 0."""
        with self._lock:
            self._prune()
            return 1 if name in self._store else 0

    def delete(self, *names: str) -> int:
        """Delete one or more keys; return count removed."""
        if not names:
            return 0
        removed = 0
        with self._lock:
            for n in names:
                if self._store.pop(n, None) is not None:
                    removed += 1
        return removed

    def ping(self) -> bool:
        """Always True for the in-memory shim."""
        return True

    def flushdb(self) -> bool:
        """Drop all keys -- exposed for test fixtures only."""
        with self._lock:
            self._store.clear()
        return True


def _now_monotonic() -> float:
    """Thin wrapper so tests can patch the clock if needed."""
    return time.monotonic()


# ---------------------------------------------------------------------------
# Singleton state
# ---------------------------------------------------------------------------

_client_lock = threading.Lock()
_client: RedisLike | None = None
_using_fallback: bool = False
_active_url: str = ""


def _try_connect_real_redis(url: str) -> RedisLike | None:
    """Attempt to construct a real ``redis.Redis`` and ping it.

    Returns the live client on success, ``None`` if the import fails or
    the server is unreachable.  Any failure here is intentional: the
    caller will downgrade to the in-memory fallback and log a WARNING.
    """
    try:
        import redis  # noqa: PLC0415 -- optional dependency, soft import
    except ImportError:
        _log.warning(
            "redis_library_unavailable",
            advisory=(
                "redis-py is not installed; falling back to in-memory shim. "
                "Install ``redis>=5`` for multi-instance deployments."
            ),
        )
        return None

    try:
        pool = redis.ConnectionPool.from_url(
            url,
            max_connections=20,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
            health_check_interval=30,
        )
        live = redis.Redis(connection_pool=pool)
        live.ping()
    except Exception as exc:  # noqa: BLE001 -- any failure -> fallback
        _log.warning(
            "redis_connection_failed",
            url=_safe_url(url),
            exc_type=type(exc).__name__,
            advisory=(
                "Could not connect to Redis; falling back to in-memory shim. "
                "Multi-instance deployments will lose blacklist + rate-limit "
                "consistency until Redis is reachable."
            ),
        )
        return None
    # ``redis.Redis`` exposes the RedisLike methods we use.
    return live  # type: ignore[return-value]


def _safe_url(url: str) -> str:
    """Strip credentials from a Redis URL for safe logging."""
    if "@" in url:
        scheme, _, rest = url.partition("://")
        _, _, host = rest.rpartition("@")
        return f"{scheme}://***@{host}" if scheme else f"***@{host}"
    return url


def get_redis_client() -> RedisLike:
    """Return the process-wide Redis client (lazy).

    On the first call:
    1. If ``GHG_REDIS_DISABLED`` is truthy, use the in-memory shim.
    2. Otherwise attempt to connect to ``REDIS_URL`` (default
       ``redis://localhost:6379/0``).  On any failure, log a WARNING
       and fall back to the in-memory shim.
    3. Subsequent calls return the cached client.

    The fallback is acceptable for unit tests and single-process dev
    runs.  Production deployments MUST set a working ``REDIS_URL`` so
    the blacklist is shared across replicas.
    """
    global _client, _using_fallback, _active_url
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:  # double-checked locking
            return _client
        url = _resolve_redis_url()
        _active_url = url
        if _force_in_memory():
            _log.warning(
                "redis_in_memory_fallback_forced",
                advisory="GHG_REDIS_DISABLED is set; using in-memory shim.",
            )
            _client = _InMemoryRedis()
            _using_fallback = True
            return _client

        real = _try_connect_real_redis(url)
        if real is not None:
            _log.info("redis_client_connected", url=_safe_url(url))
            _client = real
            _using_fallback = False
            return _client

        _client = _InMemoryRedis()
        _using_fallback = True
        return _client


def using_in_memory_fallback() -> bool:
    """Report whether the current client is the in-memory shim."""
    # Force initialisation so the caller can rely on the answer.
    get_redis_client()
    return _using_fallback


def get_storage_uri() -> str:
    """Return the URI to pass to slowapi's ``Limiter(storage_uri=...)``.

    Returns the configured ``REDIS_URL`` when a real Redis connection
    succeeded, otherwise the ``memory://`` URI so slowapi falls back to
    its own in-process backend.  The selection is consistent with
    ``get_redis_client()`` -- both either talk to the same Redis or
    both run in-process.
    """
    get_redis_client()  # force decision
    if _using_fallback:
        return "memory://"
    return _active_url


def reset_for_testing() -> None:
    """Drop the cached client so the next call re-evaluates env.

    Test-only helper.  Production code MUST NOT call this -- it would
    leak any in-flight connections held by the previous client.
    """
    global _client, _using_fallback, _active_url
    with _client_lock:
        # Best-effort flush on shutdown; ignore errors so a Redis that has
        # already gone away does not poison teardown.
        if isinstance(_client, _InMemoryRedis):
            _client.flushdb()
        _client = None
        _using_fallback = False
        _active_url = ""

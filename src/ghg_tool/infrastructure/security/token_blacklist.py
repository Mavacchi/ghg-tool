"""JWT blacklist -- SEC-P1-007.

Server-side revocation of issued JWTs.  Used by:

- ``POST /api/v1/auth/refresh``: rotation revokes the previous refresh
  ``jti``.
- ``POST /api/v1/auth/logout``: revokes the access ``jti`` *and* the
  refresh ``jti`` if available.
- ``get_current_user`` dependency: rejects any access token whose
  ``jti`` is on the blacklist.

Storage layout
--------------
Each blacklisted ``jti`` is stored as a key ``jwt:blacklist:<jti>``.
The value is the ASCII string ``"revoked"`` (no PII).  The TTL is
``exp - now()`` seconds: the entry self-expires when the original token
would have expired anyway, so the blacklist never grows unbounded.

Storage backend is provided by ``ghg_tool.infrastructure.redis_client``
which transparently falls back to an in-memory shim for unit tests and
single-process dev runs.  The fallback is logged as a WARNING.
"""

from __future__ import annotations

import time
from typing import Final

import structlog

from ghg_tool.infrastructure.redis_client import get_redis_client

_log = structlog.get_logger(__name__)

_KEY_PREFIX: Final[str] = "jwt:blacklist:"
# Minimum TTL we will accept when adding to the blacklist.  Tokens whose
# ``exp`` is in the past are effectively already invalid -- but we still
# accept them with a tiny TTL so a concurrent client that holds a clock
# skew of a few seconds cannot bypass the check.
_MIN_TTL_S: Final[int] = 5
# Safety ceiling: refuse to store entries longer than the access-token
# advisory cap (1 day).  Stops a tampered or buggy caller from polluting
# Redis with year-long blacklist entries.
_MAX_TTL_S: Final[int] = 86400 * 8  # 8 days (covers 7-day refresh + skew)


def _make_key(jti: str) -> str:
    """Build the Redis key for ``jti``.

    Args:
        jti: JWT ID (UUID string).

    Returns:
        Namespaced Redis key.
    """
    if not jti:
        raise ValueError("jti must be a non-empty string")
    return f"{_KEY_PREFIX}{jti}"


def _clamp_ttl(ttl_seconds: int) -> int:
    """Bound an arbitrary TTL into the accepted range."""
    if ttl_seconds < _MIN_TTL_S:
        return _MIN_TTL_S
    if ttl_seconds > _MAX_TTL_S:
        return _MAX_TTL_S
    return ttl_seconds


def revoke(jti: str, *, ttl_seconds: int, reason: str = "revoked") -> None:
    """Add ``jti`` to the blacklist with TTL ``ttl_seconds``.

    The TTL is clamped into ``[_MIN_TTL_S, _MAX_TTL_S]`` so a clock-skewed
    or malicious caller cannot poison the store.

    Args:
        jti: The JWT ID to revoke.
        ttl_seconds: Lifetime in seconds (typically ``exp - now``).
        reason: Reason code for log emission only -- never written to Redis.

    Raises:
        ValueError: If ``jti`` is empty.
    """
    if not jti:
        raise ValueError("jti must be a non-empty string")
    ttl = _clamp_ttl(ttl_seconds)
    client = get_redis_client()
    client.setex(_make_key(jti), ttl, "revoked")
    _log.info(
        "jwt_blacklist_revoke",
        jti_prefix=jti[:8],
        ttl_seconds=ttl,
        reason=reason,
    )


def revoke_from_claims(claims: dict[str, object], *, reason: str = "revoked") -> None:
    """Convenience wrapper -- derive TTL from a decoded JWT's ``exp`` claim.

    If ``exp`` is missing or already in the past, the TTL falls back to
    ``_MIN_TTL_S`` so the entry still gets recorded for the SIEM trail.

    Args:
        claims: A decoded JWT claims dict.
        reason: Reason code for the log line.
    """
    jti_value = claims.get("jti", "")
    jti = jti_value if isinstance(jti_value, str) else str(jti_value)
    if not jti:
        # Defensive: never raise from a revoke path -- log and bail.
        _log.warning("jwt_blacklist_revoke_missing_jti")
        return
    exp_raw = claims.get("exp")
    exp_int = 0
    if isinstance(exp_raw, (int, float)):
        exp_int = int(exp_raw)
    elif isinstance(exp_raw, str):
        try:
            exp_int = int(exp_raw)
        except ValueError:
            exp_int = 0
    now = int(time.time())
    ttl = exp_int - now if exp_int > now else _MIN_TTL_S
    revoke(jti, ttl_seconds=ttl, reason=reason)


def is_revoked(jti: str) -> bool:
    """Return True if ``jti`` is on the blacklist.

    Args:
        jti: The JWT ID to look up.

    Returns:
        True if the key exists in Redis (i.e. the token is revoked),
        False if the key is absent or ``jti`` is empty.
    """
    if not jti:
        return False
    client = get_redis_client()
    return bool(client.exists(_make_key(jti)))


def clear_for_testing(jti: str) -> None:
    """Drop a specific ``jti`` from the blacklist -- test fixture helper."""
    if not jti:
        return
    client = get_redis_client()
    client.delete(_make_key(jti))

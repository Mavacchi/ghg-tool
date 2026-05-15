"""Idempotency service — decision #6 from auto_calc_design.md §12.

Provides ``check_idempotency`` and ``store_response`` async functions used by
the ``POST /api/v1/calc/insert`` router to implement RFC-style idempotency
keys with a 24-hour TTL.

Schema: ``cache.idempotency_keys`` (migration M6 / 0026).

Columns used:
    key             VARCHAR(120) PRIMARY KEY
    tenant_id       UUID NOT NULL
    endpoint        VARCHAR(80)  NOT NULL
    request_hash    CHAR(64)     NOT NULL
    response_status INT          NOT NULL
    response_body   JSONB        NOT NULL
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
    expires_at      TIMESTAMPTZ  NOT NULL DEFAULT now() + INTERVAL '24 hours'

Scope: key collisions are per (key, tenant_id).  Two different tenants may use
the same Idempotency-Key value independently without interference.

Security: the ``request_hash`` is a SHA-256 hex digest of the canonical
(sort-keys) JSON body.  If a caller reuses a key with a *different* body we
raise ``IdempotencyKeyReusedError`` (surfaced as HTTP 422 at the router level).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_TTL_HOURS = 24
_ENDPOINT = "POST /api/v1/calc/insert"


# ---------------------------------------------------------------------------
# Custom exceptions (surfaced as 409 / 422 at router level)
# ---------------------------------------------------------------------------


class IdempotencyKeyReusedError(ValueError):
    """Raised when the same Idempotency-Key is sent with a different body.

    RFC semantics (decision #6): a key must always be paired with the same
    request body.  Reuse with a different body is a caller programming error
    and MUST be rejected with 422.
    """


@dataclass(frozen=True)
class IdempotencyHit:
    """Represents a cache hit for a previously stored idempotency key.

    Attributes:
        response_status: The HTTP status code stored for this key.
        response_body: The JSON body stored for this key.
    """

    response_status: int
    response_body: dict[str, Any]


# ---------------------------------------------------------------------------
# Hash helper
# ---------------------------------------------------------------------------


def _canonical_hash(body: dict[str, Any]) -> str:
    """Return SHA-256 hex digest of the canonical JSON representation of body.

    Canonical form: ``json.dumps`` with ``sort_keys=True`` and compact
    separators ``(",", ":")``.  This matches the spec in auto_calc_design.md §12.

    Args:
        body: The request payload as a Python dict (from Pydantic
            ``.model_dump(mode='json')``).

    Returns:
        64-character lowercase hex string (SHA-256 digest).
    """
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def check_idempotency(
    session: AsyncSession,
    *,
    key: str,
    tenant_id: str,
    body: dict[str, Any],
) -> IdempotencyHit | None:
    """Look up an idempotency key in ``cache.idempotency_keys``.

    Decision #6 logic:
        - If not found → return None (caller should proceed with insert).
        - If found and ``request_hash`` matches → return ``IdempotencyHit``
          (caller should replay the cached response).
        - If found and ``request_hash`` does NOT match → raise
          ``IdempotencyKeyReusedError`` (caller sent same key with a
          different body — programming error, 422).

    Args:
        session: Async SQLAlchemy session.
        key: Raw Idempotency-Key header value.
        tenant_id: UUID string of the requesting tenant (scope isolation).
        body: Request payload dict (used to compute the hash).

    Returns:
        ``IdempotencyHit`` if key exists with matching hash; ``None`` if
        key does not exist (or has expired).

    Raises:
        IdempotencyKeyReusedError: If the key exists but with a different
            request body hash.
    """
    request_hash = _canonical_hash(body)

    result = await session.execute(
        text(
            "SELECT request_hash, response_status, response_body "
            "FROM cache.idempotency_keys "
            "WHERE key = :key "
            "  AND tenant_id = CAST(:tenant_id AS uuid) "
            "  AND expires_at > now() "
            "LIMIT 1"
        ),
        {"key": key, "tenant_id": tenant_id},
    )
    row = result.mappings().first()

    if row is None:
        logger.debug(
            "idempotency_cache_miss",
            key=key[:16] + "...",
            tenant_id=tenant_id[:8],
        )
        return None

    stored_hash: str = str(row["request_hash"]).strip()
    if stored_hash != request_hash:
        logger.warning(
            "idempotency_key_reused_with_different_body",
            key=key[:16] + "...",
            tenant_id=tenant_id[:8],
        )
        raise IdempotencyKeyReusedError(
            f"Idempotency-Key '{key}' was previously used with a different request body. "
            "Use a new key for a different request."
        )

    logger.info(
        "idempotency_cache_hit",
        key=key[:16] + "...",
        tenant_id=tenant_id[:8],
        response_status=int(row["response_status"]),
    )
    return IdempotencyHit(
        response_status=int(row["response_status"]),
        response_body=dict(row["response_body"]),
    )


async def store_response(
    session: AsyncSession,
    *,
    key: str,
    tenant_id: str,
    body: dict[str, Any],
    response_status: int,
    response_body: dict[str, Any],
) -> None:
    """Persist a successful response in ``cache.idempotency_keys``.

    Should be called AFTER the insert has succeeded.  If the row already
    exists (race condition), the conflict is silently ignored (the first
    writer wins, which is correct idempotency behaviour).

    Args:
        session: Async SQLAlchemy session (same transaction as the insert,
            so the cache row is committed atomically with the emission row).
        key: Raw Idempotency-Key header value.
        tenant_id: UUID string of the requesting tenant.
        body: Request payload dict (used to compute the hash for future
            collision detection).
        response_status: HTTP status code to cache.
        response_body: Response JSON to cache.
    """
    request_hash = _canonical_hash(body)
    expires_at = datetime.now(UTC) + timedelta(hours=_TTL_HOURS)

    # ON CONFLICT DO NOTHING: a duplicate key can only exist if two concurrent
    # requests with the same key reached the insert step simultaneously.  The
    # first writer wins; the second gets a clean no-op.
    await session.execute(
        text(
            "INSERT INTO cache.idempotency_keys "
            "  (key, tenant_id, endpoint, request_hash, "
            "   response_status, response_body, expires_at) "
            "VALUES "
            "  (:key, CAST(:tenant_id AS uuid), :endpoint, :request_hash, "
            "   :response_status, CAST(:response_body AS jsonb), :expires_at) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {
            "key": key,
            "tenant_id": tenant_id,
            "endpoint": _ENDPOINT,
            "request_hash": request_hash,
            "response_status": response_status,
            "response_body": json.dumps(response_body),
            "expires_at": expires_at,
        },
    )
    logger.debug(
        "idempotency_key_stored",
        key=key[:16] + "...",
        tenant_id=tenant_id[:8],
        ttl_hours=_TTL_HOURS,
    )

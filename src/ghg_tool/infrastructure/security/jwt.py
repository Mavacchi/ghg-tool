"""JWT encode/decode -- SG-01, NFR-05, SEC-P1-004.

Algorithm preference:
- **RS256** (production): public key path loaded from ``GHG_JWT_PUBLIC_KEY_PATH``
  (PEM); private key from ``GHG_JWT_PRIVATE_KEY_PATH``.  RS256 allows the
  API to verify tokens without the signing secret.
- **HS256** (dev fallback): shared secret from ``GHG_JWT_SECRET``.

The validator explicitly rejects ``alg=none`` (CVE pattern) and checks
``exp`` claim.  Optional ``iss``/``aud`` claims are validated when set in
env.  Token claims carry: ``sub``, ``role``, ``tenant_id``, ``jti``,
``exp``, ``iat``, ``token_type``.

Access token TTL: 3600 s (1 h) -- NFR-05.
Refresh token TTL: 604800 s (7 d) per SEC-P1-007; configurable via
``GHG_REFRESH_TOKEN_TTL`` (seconds) or ``GHG_REFRESH_TOKEN_TTL_DAYS``.

SEC-P0-001: ``GHG_JWT_SECRET`` is mandatory in production/staging.
In development/test a deterministic fallback is used with a WARNING.
The secret must be >= 32 characters regardless of environment.

SEC-P1-004: Migrated from ``python-jose`` (CVE-2024-33664 algorithm
confusion) to ``PyJWT >= 2.8``.  Every ``jwt.decode()`` call passes an
explicit ``algorithms=[_JWT_ALGORITHM]`` list -- ``algorithm=None`` is
never used.  ``alg=none`` is rejected at the header-peek step before
``decode`` is even attempted.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any, Final, cast

import jwt  # PyJWT >= 2.8 (SEC-P1-004)
import structlog
from jwt import (
    ExpiredSignatureError,
    InvalidTokenError,
    PyJWTError,
)

_log = structlog.get_logger(__name__)

JWTError = PyJWTError

__all__ = [
    "ACCESS_TOKEN_TTL_S",
    "ExpiredSignatureError",
    "InvalidTokenError",
    "JWTError",
    "PyJWTError",
    "REFRESH_TOKEN_TTL_S",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "get_unverified_claims",
]

_PRODUCTION_LIKE_ENVS: Final[frozenset[str]] = frozenset({"production", "staging"})
_TEST_FALLBACK_SECRET: Final[str] = (
    "test-only-jwt-secret-min-32-chars-not-for-prod-xx"
)
_MIN_SECRET_LENGTH: Final[int] = 32


def _load_jwt_secret() -> str:
    """Load ``GHG_JWT_SECRET`` with environment-aware validation."""
    secret = os.environ.get("GHG_JWT_SECRET", "")
    env = os.environ.get("GHG_ENVIRONMENT", "development").lower()
    if not secret:
        if env in _PRODUCTION_LIKE_ENVS:
            raise RuntimeError(
                "GHG_JWT_SECRET must be set when GHG_ENVIRONMENT is "
                f"{env!r}; refusing to start with insecure default."
            )
        _log.warning(
            "jwt_secret_using_test_fallback",
            env=env,
            advisory="Set GHG_JWT_SECRET for non-test deployments.",
        )
        secret = _TEST_FALLBACK_SECRET
    if len(secret) < _MIN_SECRET_LENGTH:
        raise RuntimeError(
            f"GHG_JWT_SECRET must be at least {_MIN_SECRET_LENGTH} chars; "
            f"got {len(secret)}."
        )
    return secret


_JWT_ALGORITHM = os.environ.get("GHG_JWT_ALGORITHM", "HS256").upper()
_JWT_SECRET: Final[str] = _load_jwt_secret()
_JWT_PUBLIC_KEY_PATH = os.environ.get("GHG_JWT_PUBLIC_KEY_PATH", "")
_JWT_PRIVATE_KEY_PATH = os.environ.get("GHG_JWT_PRIVATE_KEY_PATH", "")
_JWT_ISSUER = os.environ.get("GHG_JWT_ISSUER", "")
_JWT_AUDIENCE = os.environ.get("GHG_JWT_AUDIENCE", "")

ACCESS_TOKEN_TTL_S: int = int(os.environ.get("GHG_ACCESS_TOKEN_TTL", "3600"))


def _resolve_refresh_ttl() -> int:
    """Resolve refresh-token TTL in seconds with multi-key precedence (SEC-P1-007)."""
    raw_seconds = os.environ.get("GHG_REFRESH_TOKEN_TTL", "")
    if raw_seconds.strip():
        return int(raw_seconds)
    raw_days = os.environ.get("GHG_REFRESH_TOKEN_TTL_DAYS", "")
    if raw_days.strip():
        return int(raw_days) * 86400
    return 7 * 86400


REFRESH_TOKEN_TTL_S: int = _resolve_refresh_ttl()


def get_unverified_claims(token: str) -> dict[str, Any]:
    """Decode JWT payload WITHOUT signature verification (routing peek only)."""
    return dict(
        jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_nbf": False,
                "verify_iat": False,
                "verify_aud": False,
                "verify_iss": False,
            },
            algorithms=[_JWT_ALGORITHM],
        )
    )


_FORBIDDEN_ALGORITHMS = frozenset({"none"})

# REQUIRED-3: the Streamlit UI uses the literal ``demo-jwt-token`` as a
# session-state sentinel when running in demo mode.  It MUST never be
# accepted by the API as a real Bearer credential.  We reject it
# unconditionally here even when GHG_ENVIRONMENT == 'development': the
# only path that legitimately accepts the sentinel is the Streamlit UI's
# *own* session_state — it is never sent over the wire to the API.
_DEMO_TOKEN_SENTINEL: Final[str] = "demo-jwt-token"  # noqa: S105 — well-known public sentinel


def _load_key(path: str) -> str:
    """Read a PEM key file from disk."""
    try:
        with open(path) as f:
            return f.read()
    except OSError as exc:
        raise RuntimeError(f"Cannot load key from {path}: {exc}") from exc


def _signing_key() -> str:
    if _JWT_ALGORITHM == "RS256":
        if not _JWT_PRIVATE_KEY_PATH:
            raise RuntimeError(
                "RS256 selected but GHG_JWT_PRIVATE_KEY_PATH is not set"
            )
        return _load_key(_JWT_PRIVATE_KEY_PATH)
    return _JWT_SECRET


def _verification_key() -> str:
    if _JWT_ALGORITHM == "RS256":
        if not _JWT_PUBLIC_KEY_PATH:
            raise RuntimeError(
                "RS256 selected but GHG_JWT_PUBLIC_KEY_PATH is not set"
            )
        return _load_key(_JWT_PUBLIC_KEY_PATH)
    return _JWT_SECRET


def _build_decode_options() -> dict[str, Any]:
    options: dict[str, Any] = {"verify_exp": True, "verify_signature": True}
    options["verify_iss"] = bool(_JWT_ISSUER)
    options["verify_aud"] = bool(_JWT_AUDIENCE)
    return options


def create_access_token(
    sub: str,
    role: str,
    tenant_id: str,
    extra_claims: dict[str, Any] | None = None,
    ttl_seconds: int | None = None,
) -> str:
    """Encode a signed JWT access token."""
    now = datetime.now(tz=UTC)
    effective_ttl = ttl_seconds if ttl_seconds is not None else ACCESS_TOKEN_TTL_S
    payload: dict[str, Any] = {
        "sub": sub,
        "role": role,
        "tenant_id": tenant_id,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": datetime.fromtimestamp(
            now.timestamp() + effective_ttl, tz=UTC
        ),
        "token_type": "access",
    }
    if _JWT_ISSUER:
        payload["iss"] = _JWT_ISSUER
    if _JWT_AUDIENCE:
        payload["aud"] = _JWT_AUDIENCE
    if extra_claims:
        _reserved = {
            "sub", "role", "tenant_id", "exp", "iat", "jti",
            "token_type", "iss", "aud",
        }
        for k, v in extra_claims.items():
            if k in _reserved:
                continue
            payload[k] = v
    # PyJWT >= 2.0 returns str (bytes in 1.x); we pin >= 2.8 so str is
    # guaranteed.  An explicit ``str()`` keeps the contract strict against any
    # bytes leak from future regressions.
    return str(jwt.encode(payload, _signing_key(), algorithm=_JWT_ALGORITHM))


def create_refresh_token(sub: str, tenant_id: str) -> str:
    """Encode a signed JWT refresh token (longer TTL, minimal claims)."""
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "sub": sub,
        "tenant_id": tenant_id,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": datetime.fromtimestamp(
            now.timestamp() + REFRESH_TOKEN_TTL_S, tz=UTC
        ),
        "token_type": "refresh",
    }
    if _JWT_ISSUER:
        payload["iss"] = _JWT_ISSUER
    if _JWT_AUDIENCE:
        payload["aud"] = _JWT_AUDIENCE
    # PyJWT >= 2.0 returns str (bytes in 1.x); we pin >= 2.8 so str is
    # guaranteed.  An explicit ``str()`` keeps the contract strict against any
    # bytes leak from future regressions.
    return str(jwt.encode(payload, _signing_key(), algorithm=_JWT_ALGORITHM))


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT, returning its claims dict.

    SEC-P1-004 / SG-01: explicit ``algorithms=[_JWT_ALGORITHM]`` allow-list;
    ``alg=none`` rejected at header-peek.

    REQUIRED-3: the Streamlit demo sentinel ``demo-jwt-token`` is rejected
    server-side before any decode attempt — it must never be honoured as a
    Bearer credential regardless of environment.
    """
    if token == _DEMO_TOKEN_SENTINEL:
        raise InvalidTokenError(
            "demo sentinel token is not a valid Bearer credential"
        )

    try:
        header = jwt.get_unverified_header(token)
    except PyJWTError as exc:
        raise PyJWTError(f"Malformed JWT header: {exc}") from exc

    alg = header.get("alg", "")
    if isinstance(alg, str) and alg.lower() in _FORBIDDEN_ALGORITHMS:
        raise ValueError(f"JWT algorithm '{alg}' is not permitted (SG-01)")

    options = _build_decode_options()
    audience = _JWT_AUDIENCE or None
    issuer = _JWT_ISSUER or None

    try:
        decoded: dict[str, Any] = jwt.decode(
            token,
            _verification_key(),
            algorithms=[_JWT_ALGORITHM],
            audience=audience,
            issuer=issuer,
            options=cast(Any, options),
        )
        return decoded
    except ExpiredSignatureError:
        raise
    except PyJWTError as exc:
        raise PyJWTError(f"JWT validation failed: {exc}") from exc

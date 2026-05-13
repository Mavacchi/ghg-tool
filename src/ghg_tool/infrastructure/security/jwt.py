"""JWT encode/decode — SG-01, NFR-05.

Algorithm preference:
- **RS256** (production): public key path loaded from ``GHG_JWT_PUBLIC_KEY_PATH``
  (PEM); private key from ``GHG_JWT_PRIVATE_KEY_PATH``.  RS256 allows the
  API to verify tokens without the signing secret.
- **HS256** (dev fallback): shared secret from ``GHG_JWT_SECRET``.

The validator explicitly rejects ``alg=none`` (CVE pattern) and checks
``exp`` claim.  Optional ``iss``/``aud`` claims are validated when set in
env.  Token claims carry: ``sub``, ``role``, ``tenant_id``, ``jti``,
``exp``, ``iat``.

Access token TTL: 3600 s (1 h) — NFR-05.
Refresh token TTL: 86400 s (24 h) — NFR-05.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

from jose import JWTError, jwt  # type: ignore[import-untyped]
from jose.exceptions import ExpiredSignatureError  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
_JWT_ALGORITHM = os.environ.get("GHG_JWT_ALGORITHM", "HS256").upper()
_JWT_SECRET = os.environ.get("GHG_JWT_SECRET", "dev-insecure-secret-replace-me")
_JWT_PUBLIC_KEY_PATH = os.environ.get("GHG_JWT_PUBLIC_KEY_PATH", "")
_JWT_PRIVATE_KEY_PATH = os.environ.get("GHG_JWT_PRIVATE_KEY_PATH", "")
_JWT_ISSUER = os.environ.get("GHG_JWT_ISSUER", "")
_JWT_AUDIENCE = os.environ.get("GHG_JWT_AUDIENCE", "")

ACCESS_TOKEN_TTL_S: int = int(os.environ.get("GHG_ACCESS_TOKEN_TTL", "3600"))
REFRESH_TOKEN_TTL_S: int = int(os.environ.get("GHG_REFRESH_TOKEN_TTL", "86400"))

# Algorithms that must never be accepted (SG-01)
_FORBIDDEN_ALGORITHMS = frozenset({"none", "NONE", "None"})


def _load_key(path: str) -> str:
    """Read a PEM key file from disk.

    Args:
        path: Filesystem path to the PEM key file.

    Returns:
        The PEM key string.

    Raises:
        RuntimeError: If the file cannot be read.
    """
    try:
        with open(path) as f:
            return f.read()
    except OSError as exc:
        raise RuntimeError(f"Cannot load key from {path}: {exc}") from exc


def _signing_key() -> str:
    """Return the active signing key (private key for RS256, secret for HS256)."""
    if _JWT_ALGORITHM == "RS256":
        if not _JWT_PRIVATE_KEY_PATH:
            raise RuntimeError(
                "RS256 selected but GHG_JWT_PRIVATE_KEY_PATH is not set"
            )
        return _load_key(_JWT_PRIVATE_KEY_PATH)
    return _JWT_SECRET


def _verification_key() -> str:
    """Return the active verification key (public key for RS256, secret for HS256)."""
    if _JWT_ALGORITHM == "RS256":
        if not _JWT_PUBLIC_KEY_PATH:
            raise RuntimeError(
                "RS256 selected but GHG_JWT_PUBLIC_KEY_PATH is not set"
            )
        return _load_key(_JWT_PUBLIC_KEY_PATH)
    return _JWT_SECRET


def _build_options() -> dict[str, Any]:
    """Build jose decode options dict, setting iss/aud verification as configured."""
    options: dict[str, Any] = {"verify_exp": True}
    if not _JWT_ISSUER:
        options["verify_iss"] = False
    if not _JWT_AUDIENCE:
        options["verify_aud"] = False
    return options


def create_access_token(
    sub: str,
    role: str,
    tenant_id: str,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Encode a signed JWT access token.

    Args:
        sub: Subject claim — typically the user UUID string.
        role: RBAC role code.
        tenant_id: Tenant UUID string.
        extra_claims: Additional claims merged into the payload (optional).

    Returns:
        Signed JWT string.
    """
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "sub": sub,
        "role": role,
        "tenant_id": tenant_id,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": datetime.fromtimestamp(
            now.timestamp() + ACCESS_TOKEN_TTL_S, tz=UTC
        ),
        "token_type": "access",
    }
    if _JWT_ISSUER:
        payload["iss"] = _JWT_ISSUER
    if _JWT_AUDIENCE:
        payload["aud"] = _JWT_AUDIENCE
    if extra_claims:
        payload.update(extra_claims)
    return str(jwt.encode(payload, _signing_key(), algorithm=_JWT_ALGORITHM))


def create_refresh_token(sub: str, tenant_id: str) -> str:
    """Encode a signed JWT refresh token (longer TTL, minimal claims).

    Args:
        sub: Subject claim — user UUID string.
        tenant_id: Tenant UUID string.

    Returns:
        Signed JWT string for the refresh flow.
    """
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
    return str(jwt.encode(payload, _signing_key(), algorithm=_JWT_ALGORITHM))


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT, returning its claims dict.

    Explicitly rejects ``alg=none`` regardless of jose library version.

    Args:
        token: The raw JWT string from the ``Authorization: Bearer`` header.

    Returns:
        The decoded claims dict.

    Raises:
        ValueError: If the algorithm is ``none`` or another forbidden value.
        ExpiredSignatureError: If the token has expired (re-raised as-is).
        JWTError: For any other JWT validation failure.
    """
    # Peek at the header BEFORE decoding to reject alg=none (SG-01)
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise JWTError(f"Malformed JWT header: {exc}") from exc

    alg = header.get("alg", "")
    if alg in _FORBIDDEN_ALGORITHMS:
        raise ValueError(f"JWT algorithm '{alg}' is not permitted (SG-01)")

    options = _build_options()
    audiences = [_JWT_AUDIENCE] if _JWT_AUDIENCE else None

    try:
        return jwt.decode(  # type: ignore[no-any-return]  # jose has no stubs
            token,
            _verification_key(),
            algorithms=[_JWT_ALGORITHM],
            audience=audiences,
            issuer=_JWT_ISSUER or None,
            options=options,
        )
    except ExpiredSignatureError:
        raise
    except JWTError as exc:
        raise JWTError(f"JWT validation failed: {exc}") from exc

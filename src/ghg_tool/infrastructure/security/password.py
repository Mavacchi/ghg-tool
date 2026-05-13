"""Password hashing with bcrypt — SG-04.

Uses the ``bcrypt`` library directly to avoid passlib's version-detection
incompatibility with bcrypt >= 4.x (passlib 1.7.4 inspects ``__about__``
which was removed in newer bcrypt releases).

Passwords MUST NEVER be logged, stored in plaintext, or echoed in API
responses.  Only the hash is persisted in ``ref.users.password_hash``.

The work factor ``_ROUNDS = 12`` balances security and latency; adjust via
the ``GHG_BCRYPT_ROUNDS`` env var in future if required (NFR-06).
"""

from __future__ import annotations

import bcrypt

_ROUNDS: int = 12


def hash_password(plain: str) -> str:
    """Return the bcrypt hash of *plain*.

    Args:
        plain: The raw password string (never logged or returned).

    Returns:
        A bcrypt hash string suitable for storage in ``ref.users.password_hash``.
    """
    salt = bcrypt.gensalt(rounds=_ROUNDS)
    return bcrypt.hashpw(plain.encode(), salt).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify *plain* against *hashed* using constant-time comparison.

    Args:
        plain: The raw password provided by the user.
        hashed: The bcrypt hash stored in the database.

    Returns:
        True if the password matches; False otherwise.
    """
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:  # noqa: BLE001 — invalid hash format → treat as wrong password
        return False

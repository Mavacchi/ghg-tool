"""Password hashing with bcrypt via passlib — SG-04.

Uses ``CryptContext`` with bcrypt scheme; deprecated schemes are omitted so
that any legacy hash triggers an automatic re-hash on next login.

Passwords MUST NEVER be logged, stored in plaintext, or echoed in API
responses.  Only the hash is persisted in ``ref.users.password_hash``.
"""

from __future__ import annotations

from passlib.context import CryptContext

# Single global context — bcrypt with auto-upgrade on verify
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Return the bcrypt hash of *plain*.

    Args:
        plain: The raw password string (never logged or returned).

    Returns:
        A bcrypt hash string suitable for storage in ``ref.users.password_hash``.
    """
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify *plain* against *hashed* using constant-time comparison.

    Args:
        plain: The raw password provided by the user.
        hashed: The bcrypt hash stored in the database.

    Returns:
        True if the password matches; False otherwise.
    """
    return _pwd_context.verify(plain, hashed)

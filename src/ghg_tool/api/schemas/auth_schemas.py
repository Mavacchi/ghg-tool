"""Pydantic v2 schemas for /auth endpoints (SG-01, NFR-05)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    """Credentials payload for ``POST /api/v1/auth/login``.

    Attributes:
        username: Application username (not email).
        password: Raw password -- never echoed or logged.
        tenant_code: Optional tenant discriminator.  When two tenants share
            the same username (unique constraint is per-tenant, not global)
            this field disambiguates the lookup.  S-027.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=200)
    tenant_code: str | None = Field(default=None, max_length=80)

    @field_validator("username")
    @classmethod
    def username_no_whitespace(cls, v: str) -> str:
        """Reject usernames with leading/trailing whitespace.

        Args:
            v: Raw username value.

        Returns:
            Stripped username string.

        Raises:
            ValueError: If the stripped value is empty.
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("username must not be blank")
        return stripped


class TokenResponse(BaseModel):
    """Response body for successful login and token refresh.

    Attributes:
        access_token: Short-lived JWT (1 h per NFR-05).
        refresh_token: Long-lived JWT for silent re-auth (24 h per NFR-05).
        expires_in: Access token TTL in seconds.
        token_type: Always ``'bearer'``.
    """

    model_config = ConfigDict(frozen=True)

    access_token: str = Field(description="JWT access token")
    refresh_token: str = Field(description="JWT refresh token (24 h)")
    expires_in: int = Field(description="Access token TTL in seconds")
    token_type: str = Field(default="bearer")


class RefreshRequest(BaseModel):
    """Payload for ``POST /api/v1/auth/refresh``.

    Attributes:
        refresh_token: A valid, unexpired refresh JWT.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    refresh_token: str = Field(min_length=1)

class LogoutRequest(BaseModel):
    """Optional payload for ``POST /api/v1/auth/logout``.

    SEC-P1-007: when the caller wishes to revoke their refresh token in
    addition to the bearer access token, they post the refresh JWT here.
    The handler is idempotent and the body is optional -- legacy clients
    can still call /logout with no body and get a 204.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    refresh_token: str | None = Field(default=None, min_length=1)

"""Pydantic v2 schemas for /api/v1/users endpoints.

Covers admin CRUD operations: activate/deactivate, role change, and
password reset.  All schemas use ``extra="forbid"`` to reject unexpected
fields at the Pydantic boundary before the handler runs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RoleCode = Literal["data_steward", "esg_manager", "auditor"]


class UserActivePatchRequest(BaseModel):
    """Body for ``PATCH /api/v1/users/{user_uuid}/active``.

    Attributes:
        is_active: Desired activation state for the target user.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    is_active: bool


class UserRolePatchRequest(BaseModel):
    """Body for ``PATCH /api/v1/users/{user_uuid}/role``.

    Attributes:
        role_code: New role code to assign to the target user.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    role_code: RoleCode


class UserPasswordResetRequest(BaseModel):
    """Body for ``POST /api/v1/users/{user_uuid}/password-reset``.

    When ``new_password`` is null or omitted the server generates a
    secure 16-character random password server-side.

    Attributes:
        new_password: Explicit new password (8-200 chars), or None to
            trigger server-side generation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    new_password: str | None = Field(default=None, min_length=8, max_length=200)


class UserPasswordResetResponse(BaseModel):
    """Response for a successful password reset.

    The plaintext password is returned ONCE so the admin can communicate
    it to the user.  It is never logged, never stored, and never returned
    again after this single response.

    Attributes:
        new_password: The new plaintext password (single-use response).
    """

    model_config = ConfigDict(frozen=True)

    new_password: str

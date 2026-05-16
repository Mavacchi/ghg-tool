"""Pydantic v2 schemas for /api/v1/users endpoints.

Covers admin CRUD operations: activate/deactivate, role change, password
reset, and GDPR Art. 17 erasure (pseudonymisation).  All schemas use
``extra="forbid"`` to reject unexpected fields at the Pydantic boundary
before the handler runs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RoleCode = Literal["editor", "admin", "viewer"]


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


class UserErasureResponse(BaseModel):
    """Response for a successful GDPR Art. 17 erasure (pseudonymisation).

    The user row is NOT deleted (required for audit-trail retention under
    CSRD Art. 23(2) and GDPR Art. 6(1)(c)).  PII fields are replaced with
    a deterministic pseudonym derived from the user UUID so that:
    - The user can no longer log in (``password_hash = '!erased'``).
    - Audit log entries linking ``user_id`` FK remain intact and valid.
    - The pseudonym is reproducible from the UUID for DPA enquiries.

    Attributes:
        user_id: UUID of the erased user row.
        pseudonym: The sentinel string used to replace username/email.
        erased_at: UTC timestamp when the erasure was applied.
    """

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    pseudonym: str
    erased_at: datetime

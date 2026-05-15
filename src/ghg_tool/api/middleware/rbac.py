"""RBAC helper middleware — SG-02, FR-31.

This module exposes ``require_role`` and ``require_permission`` FastAPI
dependency factories used directly in route handlers.  The middleware layer
itself is thin (the heavy lifting is in the auth dependency + DB RLS).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, status

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.infrastructure.security.rbac import is_permitted


def require_role(*allowed_roles: str) -> Callable[..., Any]:
    """FastAPI dependency factory that enforces role-based access.

    Usage::

        @router.post("/")
        async def create(..., _: CurrentUser = Depends(require_role("editor"))):
            ...

    Args:
        *allowed_roles: One or more role code strings that are permitted.

    Returns:
        A FastAPI dependency callable that returns the current user or raises 403.
    """
    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        """Inner dependency that validates the user's role.

        Args:
            user: The decoded, authenticated current user.

        Returns:
            The current user if the role is permitted.

        Raises:
            HTTPException: 403 Forbidden if the role is not in the allowed set.
        """
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "type": "about:blank",
                    "title": "Forbidden",
                    "status": 403,
                    "detail": (
                        f"Role '{user.role}' is not permitted for this operation. "
                        f"Required: {sorted(allowed_roles)}"
                    ),
                },
            )
        return user

    return _dep


def require_permission(resource: str, action: str) -> Callable[..., Any]:
    """FastAPI dependency factory using the RBAC permission matrix.

    This is an alternative to ``require_role`` that uses the structured
    ``PERMISSION_MATRIX`` in ``infrastructure/security/rbac.py``.

    Args:
        resource: Resource identifier (e.g. 'emissions').
        action: Action identifier (e.g. 'write').

    Returns:
        A FastAPI dependency callable that returns the current user or raises 403.
    """
    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        """Inner dependency that checks the permission matrix.

        Args:
            user: The decoded, authenticated current user.

        Returns:
            The current user if permitted.

        Raises:
            HTTPException: 403 Forbidden if the role lacks the permission.
        """
        if not is_permitted(user.role, resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "type": "about:blank",
                    "title": "Forbidden",
                    "status": 403,
                    "detail": (
                        f"Role '{user.role}' cannot perform '{action}' on '{resource}'."
                    ),
                },
            )
        return user

    return _dep

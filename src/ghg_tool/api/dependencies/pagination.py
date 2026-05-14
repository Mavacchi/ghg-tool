"""Pagination dependency helpers — cursor-based pagination for list endpoints."""

from __future__ import annotations

import base64
import json
import uuid

from fastapi import HTTPException, Query, status


class CursorParams:
    """Cursor-based pagination parameters for list endpoints.

    Attributes:
        cursor: Opaque base64-encoded cursor string from a previous response.
        limit: Maximum number of items to return (1–500).
    """

    def __init__(
        self,
        cursor: str | None = Query(default=None, description="Pagination cursor"),
        limit: int = Query(default=50, ge=1, le=500, description="Page size"),
    ) -> None:
        """Initialise with query parameter values.

        Args:
            cursor: Optional opaque cursor from the previous page.
            limit: Page size (1–500, default 50).
        """
        self.cursor = cursor
        self.limit = limit

    def decode_cursor(self) -> dict[str, str]:
        """Decode the opaque cursor to a filter dict.

        Returns:
            A dict with cursor fields, or empty dict if the cursor is None.

        Raises:
            HTTPException: 400 when a non-empty cursor cannot be decoded —
                silently returning an empty dict here would let the client
                walk page 1 forever without an error signal.
        """
        if not self.cursor:
            return {}
        # Local import keeps the dependency tree free of an API → middleware
        # cycle at module import time.
        from ghg_tool.api.middleware.correlation_id import get_correlation_id

        problem_detail = {
            "type": "about:blank",
            "title": "Bad Request",
            "status": 400,
            "detail": "Invalid pagination cursor",
            "correlation_id": get_correlation_id(),
        }
        try:
            payload = base64.urlsafe_b64decode(self.cursor.encode()).decode()
            decoded = json.loads(payload)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=problem_detail,
            ) from exc
        if not isinstance(decoded, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=problem_detail,
            )
        return decoded  # type: ignore[no-any-return]


def encode_cursor(last_id: uuid.UUID | str) -> str:
    """Encode a primary key UUID into an opaque cursor string.

    Args:
        last_id: The ``id`` of the last item on the current page.

    Returns:
        A base64url-encoded JSON cursor string.
    """
    payload = json.dumps({"after_id": str(last_id)})
    return base64.urlsafe_b64encode(payload.encode()).decode()

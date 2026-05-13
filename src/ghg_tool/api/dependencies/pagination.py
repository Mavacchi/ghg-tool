"""Pagination dependency helpers — cursor-based pagination for list endpoints."""

from __future__ import annotations

import base64
import json
import uuid

from fastapi import Query


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
            A dict with cursor fields, or empty dict if cursor is None/invalid.
        """
        if not self.cursor:
            return {}
        try:
            payload = base64.urlsafe_b64decode(self.cursor.encode()).decode()
            return json.loads(payload)  # type: ignore[no-any-return]
        except Exception:  # noqa: BLE001
            return {}


def encode_cursor(last_id: uuid.UUID | str) -> str:
    """Encode a primary key UUID into an opaque cursor string.

    Args:
        last_id: The ``id`` of the last item on the current page.

    Returns:
        A base64url-encoded JSON cursor string.
    """
    payload = json.dumps({"after_id": str(last_id)})
    return base64.urlsafe_b64encode(payload.encode()).decode()

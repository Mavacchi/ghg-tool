"""Correlation-ID middleware — FR-22, NFR-08.

Reads ``X-Correlation-ID`` from the incoming request header; generates a
UUID v4 if absent.  The value is stored in a context variable so that every
log entry and downstream call can reference it.  The resolved ID is echoed in
the response header.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

#: Module-level context variable for the current request's correlation ID.
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")

HEADER_NAME = "X-Correlation-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware that attaches a ``correlation_id`` to every request.

    If the client sends ``X-Correlation-ID``, that value is used (after
    validation that it is a valid UUID string); otherwise a fresh UUID v4 is
    generated.  The resolved ID is:

    - stored in ``correlation_id_var`` ContextVar (available to loggers),
    - echoed in the ``X-Correlation-ID`` response header.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process the request, injecting correlation ID.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            The HTTP response with the ``X-Correlation-ID`` header set.
        """
        raw_id = request.headers.get(HEADER_NAME, "")
        correlation_id = _resolve_correlation_id(raw_id)
        correlation_id_var.set(correlation_id)

        response = await call_next(request)
        response.headers[HEADER_NAME] = correlation_id
        return response


def _resolve_correlation_id(raw: str) -> str:
    """Return a valid UUID string, generating one if *raw* is absent/invalid.

    Args:
        raw: The raw header value (may be empty string or malformed UUID).

    Returns:
        A valid UUID string.
    """
    if raw:
        try:
            return str(uuid.UUID(raw))
        except ValueError:
            pass
    return str(uuid.uuid4())


def get_correlation_id() -> str:
    """Return the current request's correlation ID from the context variable.

    Returns:
        The correlation ID string; empty string outside a request context.
    """
    return correlation_id_var.get()

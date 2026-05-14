"""RFC 7807 error-handler middleware — NFR-09 A02.

Catches all unhandled exceptions and converts them to
``application/problem+json`` responses.  Stack traces are NEVER
exposed to the client.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from ghg_tool.api.middleware.correlation_id import get_correlation_id

logger = structlog.get_logger(__name__)

_PROBLEM_CONTENT_TYPE = "application/problem+json"


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Global exception-to-problem+json mapper.

    Catches any unhandled ``Exception`` that escapes the route handlers,
    logs it server-side with ``correlation_id`` (no PII, no stack trace in
    response), and returns a well-formed RFC 7807 payload.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Wrap the request/response cycle in a catch-all error handler.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            The response, or an RFC 7807 problem response on unhandled exceptions.
        """
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001
            correlation_id = get_correlation_id() or str(uuid.uuid4())
            log = logger.bind(correlation_id=correlation_id, route=str(request.url))
            log.exception("Unhandled exception", exc_type=type(exc).__name__)
            return _problem_response(
                status=500,
                title="Internal Server Error",
                detail="An unexpected error occurred. Please contact support.",
                correlation_id=correlation_id,
            )


def _problem_response(
    *,
    status: int,
    title: str,
    detail: str,
    correlation_id: str,
    type_uri: str = "about:blank",
) -> JSONResponse:
    """Build a JSONResponse conforming to RFC 7807.

    Args:
        status: HTTP status code.
        title: Short problem summary.
        detail: Human-readable detail for this occurrence.
        correlation_id: Correlation UUID string for log tracing.
        type_uri: URI identifying the problem type.

    Returns:
        A JSONResponse with ``Content-Type: application/problem+json``.
    """
    body = {
        "type": type_uri,
        "title": title,
        "status": status,
        "detail": detail,
        "correlation_id": correlation_id,
    }
    return JSONResponse(
        content=body,
        status_code=status,
        headers={"Content-Type": _PROBLEM_CONTENT_TYPE},
    )


def build_problem_response(
    status: int,
    title: str,
    detail: str,
    correlation_id: str | None = None,
) -> JSONResponse:
    """Public helper for constructing RFC 7807 responses in route handlers.

    Args:
        status: HTTP status code.
        title: Short problem summary.
        detail: Human-readable explanation.
        correlation_id: Optional correlation UUID string.

    Returns:
        JSONResponse with ``Content-Type: application/problem+json``.
    """
    _cid = correlation_id or get_correlation_id() or str(uuid.uuid4())
    return _problem_response(
        status=status,
        title=title,
        detail=detail,
        correlation_id=_cid,
    )

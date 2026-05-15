"""Security response-headers middleware — SEC-P1-002.

Injects standard HTTP security headers into every response:

- ``Strict-Transport-Security`` — HSTS; enforces HTTPS for 1 year.
- ``X-Content-Type-Options`` — prevents MIME-type sniffing.
- ``X-Frame-Options`` — blocks clickjacking via iframes.
- ``Referrer-Policy`` — suppresses Referer header on cross-origin requests.
- ``Content-Security-Policy`` — restricts resource loading to same-origin
  by default; tighten per page in future iterations.

These headers are additive — they do not replace any header already set by
a downstream middleware or route handler.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_SECURITY_HEADERS: dict[str, str] = {
    # HSTS: enforce HTTPS for 1 year including all sub-domains; preload eligible.
    # ``preload`` enables submission to browser HSTS preload lists (S-020).
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    # Prevent browsers from MIME-sniffing the content-type.
    "X-Content-Type-Options": "nosniff",
    # Block embedding in <iframe> / <frame> / <object> to prevent clickjacking.
    "X-Frame-Options": "DENY",
    # Do not send Referer header on cross-origin requests.
    "Referrer-Policy": "no-referrer",
    # Restrict resource loading to same origin by default.
    "Content-Security-Policy": "default-src 'self'",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that injects standard HTTP security headers into every response.

    Headers are only set when not already present, so route handlers can
    override individual headers if needed (e.g., a future CSP nonce endpoint).
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Inject security headers into the outgoing response.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            The HTTP response with security headers added.
        """
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            if header not in response.headers:
                response.headers[header] = value
        return response

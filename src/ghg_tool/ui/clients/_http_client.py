"""Centralised HTTP wrapper for UI API clients.

Provides ``safe_request`` — a single entry point for GET, POST, PATCH, and
DELETE requests that handles ``httpx.HTTPStatusError`` and
``httpx.RequestError`` uniformly.

Design rationale
----------------
All four UI clients (tenant_admin_client, sites_client, hotspot_client,
api_client) previously duplicated the same try/except boilerplate.
This module extracts that logic once so each client calls ``safe_request``
instead of repeating the pattern.

The ``_httpx`` parameter allows callers to inject their own ``httpx``
import reference.  This is necessary because the test suite patches
``httpx.get`` / ``httpx.post`` etc. on the *caller* module's namespace
(e.g. ``ghg_tool.ui.clients.tenant_admin_client.httpx.get``).  By
accepting the caller's ``httpx`` reference the helper stays transparent
to the existing test patches without requiring any test changes.

No GHG calculations are performed here.
"""

from __future__ import annotations

from typing import Any

import httpx as _default_httpx


def safe_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
    _httpx: Any = _default_httpx,
) -> dict[str, Any]:
    """Centralised HTTP wrapper — returns dict (data or error).

    Performs one HTTP request using the specified method and returns the
    parsed JSON response on success.  On failure returns an error dict
    rather than raising, so callers can display the error in the UI.

    Args:
        method: HTTP method string — ``"GET"``, ``"POST"``, ``"PATCH"``,
            or ``"DELETE"`` (case-insensitive).
        url: Full URL to request.
        headers: Request headers (must include ``Authorization`` if required).
        body: Optional JSON-serialisable request body (POST/PATCH only).
        params: Optional query parameters (GET only).
        timeout: Request timeout in seconds (default 30.0).
        _httpx: httpx module reference (default is the module-level import;
            callers may pass their own reference so test patches apply).

    Returns:
        Parsed JSON dict on success.
        ``{"error": "...", "status_code": int}`` on HTTP error.
        ``{"error": "..."}`` on network/connection error.
    """
    method_upper = method.upper()
    try:
        if method_upper == "GET":
            resp = _httpx.get(url, headers=headers, params=params, timeout=timeout)
        elif method_upper == "POST":
            resp = _httpx.post(url, headers=headers, json=body, timeout=timeout)
        elif method_upper == "PATCH":
            resp = _httpx.patch(url, headers=headers, json=body, timeout=timeout)
        elif method_upper == "DELETE":
            resp = _httpx.delete(url, headers=headers, timeout=timeout)
        else:
            raise ValueError(f"Unsupported HTTP method: {method!r}")  # noqa: TRY301
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]
    except _httpx.HTTPStatusError as exc:
        return {"error": str(exc), "status_code": exc.response.status_code}
    except _httpx.RequestError as exc:
        return {"error": str(exc)}

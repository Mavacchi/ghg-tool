"""HTTP client for GET /api/v1/analysis/hotspots.

Wraps the hotspot analysis endpoint introduced in wave 4.  Returns the raw
JSON dict from the API; no GHG calculations are performed here.

The response has the shape::

    {
        "anno": 2025,
        "top_n": 5,
        "total_scope3_tco2e": "1234.56",
        "hotspots": [
            {
                "rank": 1,
                "sub_scope": "Cat1",
                "category_label": "Cat 1 — Acquisto beni/servizi",
                "tco2e": "800.00",
                "pct_of_scope3": "64.80",
                "cumulative_pct": "64.80",
                "yoy_delta_pct": "5.2",
                "flag_high_concentration": true,
                "flag_yoy_outlier": false,
                "priority": "HIGH",
                "gwp_set": "AR6",
                "calc_timestamp": "2025-01-15T10:00:00Z",
                "factor_sources": ["ecoinvent", "EXIOBASE"],
            },
            ...
        ],
        "flag_high_concentration": true,
        "factor_sources": ["ecoinvent", "EXIOBASE"],
        "gwp_set": "AR6",
        "methodology": "GHG Protocol Scope 3 Standard §10",
        "calc_timestamp": "2025-01-15T10:00:00Z",
    }

Cache TTL is 60 seconds (1 min) per task specification.

No GHG calculations are performed here.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

_DEFAULT_BASE_URL = os.environ.get("GHG_API_BASE_URL", "http://localhost:8000")
_TIMEOUT = 30.0


def _get_base_url() -> str:
    return st.session_state.get("api_base_url", _DEFAULT_BASE_URL)


def _get_auth_headers() -> dict[str, str]:
    """Build auth headers using the JWT token from session_state."""
    from ghg_tool.ui.streamlit_app.lib.auth import _DEMO_MODE, _DEMO_TOKEN  # noqa: PLC0415

    token = st.session_state.get("token")
    if not token:
        token = _DEMO_TOKEN if _DEMO_MODE else None
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


@st.cache_data(ttl=60, show_spinner=False)
def fetch_hotspots(anno: int, top_n: int = 5) -> dict[str, Any]:
    """Fetch Scope 3 hot-spot analysis from ``GET /api/v1/analysis/hotspots``.

    Cache TTL is 60 seconds (1 min) per wave-4 spec.  Results are scoped
    to the authenticated tenant via the JWT claim.

    Args:
        anno: Reporting year to analyse.
        top_n: Number of top categories to return (3..10).

    Returns:
        Parsed JSON response dict on success.
        ``{"error": "not_found", "status_code": 404}`` when no Scope 3 data
        exists for the year.
        ``{"error": "...", "status_code": N}`` for other HTTP errors.
        ``{"error": "..."}`` on network failure.

    No GHG calculations are performed here.
    """
    try:
        resp = httpx.get(
            f"{_get_base_url()}/api/v1/analysis/hotspots",
            headers=_get_auth_headers(),
            params={"anno": anno, "top_n": top_n},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]
    except httpx.HTTPStatusError as exc:
        return {
            "error": str(exc),
            "status_code": exc.response.status_code,
        }
    except httpx.RequestError as exc:
        return {"error": str(exc)}

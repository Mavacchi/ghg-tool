"""PDF data loader — fetches report data from DB (read-only) for PDF generation.

This module assembles the ``report_data`` dict consumed by ``PDFBuilder.build()``.
It reads ONLY from the DB via the API client or direct DB sessions.
No emission calculations are performed here.
"""

from __future__ import annotations

from typing import Any


def load_report_data(
    *,
    anno: int,
    gwp_set: str = "AR6",
    language: str = "it",
    api_base_url: str = "http://localhost:8000",
    token: str = "",
) -> dict[str, Any]:
    """Assemble report_data by fetching from the backend API.

    All network calls are synchronous (for WeasyPrint compatibility).

    Args:
        anno: Reporting year.
        gwp_set: GWP set string.
        language: Report language ('it' or 'en').
        api_base_url: Backend API base URL.
        token: JWT Bearer token.

    Returns:
        Dict suitable for passing to ``PDFBuilder.build()``.
    """
    import httpx

    headers = {"Authorization": f"Bearer {token}"}
    timeout = 30.0

    def _get(path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            resp = httpx.get(
                f"{api_base_url}{path}",
                headers=headers,
                params=params,
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.RequestError):
            return {}

    emissions_raw = _get("/api/v1/emissions/", {
        "anno": anno, "gwp_set": gwp_set, "limit": 500
    })
    all_emissions: list[dict[str, Any]] = emissions_raw.get("items", [])

    biogenic = [
        r for r in all_emissions
        if r.get("co2_biogenic_tonne") and float(r.get("co2_biogenic_tonne", 0)) > 0
    ]

    factors_raw = _get("/api/v1/factor-catalog/", {"limit": 200})
    factors: list[dict[str, Any]] = factors_raw.get("items", [])

    dq_raw = _get("/api/v1/dq-findings/", {
        "resolution_status": "OPEN", "limit": 100
    })
    dq_findings: list[dict[str, Any]] = dq_raw.get("items", [])
    waived_raw = _get("/api/v1/dq-findings/", {
        "resolution_status": "WAIVED", "limit": 100
    })
    dq_findings += waived_raw.get("items", [])

    audit_raw = _get("/api/v1/audit-trail/", {"anno": anno, "limit": 500})
    audit_trail: list[dict[str, Any]] = audit_raw.get("entries", [])

    return {
        "anno": anno,
        "gwp_set": gwp_set,
        "language": language,
        "emissions": all_emissions,
        "biogenic": biogenic,
        "factors": factors,
        "dq_findings": dq_findings,
        "audit_trail": audit_trail,
        "intensity_rows": [],  # populated when /api/v1/intensity becomes available
    }

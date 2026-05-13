"""Typed HTTP client wrapping all 7 backend API endpoints (FR-29).

All calls use httpx, attach the JWT Bearer token from session_state,
and are decorated with ``@st.cache_data(ttl=300)`` to reduce load on
the backend (NFR-02).

No emission calculations are performed here — the client is a pure
consumer of pre-calculated data from the API.

Endpoints consumed:
  GET  /api/v1/kpis
  GET  /api/v1/emissions
  GET  /api/v1/audit-trail
  GET  /api/v1/factor-catalog
  GET  /api/v1/dq-findings
  POST /api/v1/dq-findings/waiver/{finding_id}
  POST /api/v1/emissions/correction
  GET  /api/v1/reports/status/{job_id}
  POST /api/v1/reports/pdf
  POST /api/v1/reports/excel
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd
import streamlit as st

_DEFAULT_BASE_URL = os.environ.get("GHG_API_BASE_URL", "http://localhost:8000")
_TIMEOUT = 30.0


def _get_base_url() -> str:
    return st.session_state.get("api_base_url", _DEFAULT_BASE_URL)


def _get_headers() -> dict[str, str]:
    token = st.session_state.get("token", "demo-jwt-token")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _safe_get(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Perform a GET request with auth; return parsed JSON or empty dict on error.

    Args:
        url: Full URL to request.
        params: Optional query parameters.

    Returns:
        Parsed JSON response or empty dict on network/auth error.
    """
    try:
        resp = httpx.get(url, headers=_get_headers(), params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPStatusError, httpx.RequestError):
        return {}


def _safe_post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    """Perform a POST request with auth; return parsed JSON or error dict.

    Args:
        url: Full URL to request.
        body: JSON-serialisable request body.

    Returns:
        Parsed JSON response or ``{"error": "..."}`` on failure.
    """
    try:
        resp = httpx.post(url, headers=_get_headers(), json=body, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        return {"error": str(exc), "status_code": exc.response.status_code}
    except httpx.RequestError as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Cached API calls (st.cache_data with 300 s TTL per constraint #10)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300, show_spinner=False)
def fetch_kpis(anno: int | None = None, gwp_set: str = "AR6") -> dict[str, Any]:
    """Fetch KPI summary from ``GET /api/v1/kpis``.

    Args:
        anno: Optional year filter.
        gwp_set: GWP set (default 'AR6').

    Returns:
        KpiSummaryResponse JSON dict.
    """
    params: dict[str, Any] = {"gwp_set": gwp_set}
    if anno is not None:
        params["anno"] = anno
    return _safe_get(f"{_get_base_url()}/api/v1/kpis/", params=params)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_emissions(
    scope: int | None = None,
    anno: int | None = None,
    codice_sito: str | None = None,
    sub_scope: str | None = None,
    gwp_set: str = "AR6",
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Fetch emission rows from ``GET /api/v1/emissions``.

    Args:
        scope: Optional scope filter (1, 2, or 3).
        anno: Optional year filter.
        codice_sito: Optional site filter.
        sub_scope: Optional sub-scope filter.
        gwp_set: GWP set.
        limit: Page size (max 500).

    Returns:
        List of EmissionResponse dicts.
    """
    params: dict[str, Any] = {"gwp_set": gwp_set, "limit": limit}
    if scope is not None:
        params["scope"] = scope
    if anno is not None:
        params["anno"] = anno
    if codice_sito:
        params["codice_sito"] = codice_sito
    if sub_scope:
        params["sub_scope"] = sub_scope
    data = _safe_get(f"{_get_base_url()}/api/v1/emissions/", params=params)
    return data.get("items", [])


@st.cache_data(ttl=300, show_spinner=False)
def fetch_audit_trail(
    anno: int | None = None,
    codice_sito: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Fetch audit trail from ``GET /api/v1/audit-trail``.

    Args:
        anno: Optional year filter.
        codice_sito: Optional site filter.
        limit: Max rows.

    Returns:
        AuditTrailResponse JSON dict.
    """
    params: dict[str, Any] = {"limit": limit}
    if anno is not None:
        params["anno"] = anno
    if codice_sito:
        params["codice_sito"] = codice_sito
    return _safe_get(f"{_get_base_url()}/api/v1/audit-trail/", params=params)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_factor_catalog(
    scope: int | None = None,
    source: str | None = None,
    gwp_set: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Fetch factor catalog entries from ``GET /api/v1/factor-catalog``.

    Args:
        scope: Optional scope filter.
        source: Optional source filter.
        gwp_set: Optional GWP set filter.
        limit: Max rows.

    Returns:
        List of FactorCatalogResponse dicts.
    """
    params: dict[str, Any] = {"limit": limit}
    if scope is not None:
        params["scope"] = scope
    if source:
        params["source"] = source
    if gwp_set:
        params["gwp_set"] = gwp_set
    data = _safe_get(f"{_get_base_url()}/api/v1/factor-catalog/", params=params)
    return data.get("items", [])


@st.cache_data(ttl=300, show_spinner=False)
def fetch_dq_findings(
    severity: str | None = None,
    resolution_status: str | None = None,
    rule_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Fetch DQ findings from ``GET /api/v1/dq-findings``.

    Args:
        severity: Optional severity filter ('CRIT', 'WARN', 'INFO').
        resolution_status: Optional status filter.
        rule_id: Optional rule ID filter.
        limit: Max rows.

    Returns:
        List of DqFindingResponse dicts.
    """
    params: dict[str, Any] = {"limit": limit}
    if severity:
        params["severity"] = severity
    if resolution_status:
        params["resolution_status"] = resolution_status
    if rule_id:
        params["rule_id"] = rule_id
    data = _safe_get(f"{_get_base_url()}/api/v1/dq-findings/", params=params)
    return data.get("items", [])


def post_waiver(finding_id: str, reason_code: str, justification: str) -> dict[str, Any]:
    """Apply a waiver to a DQ finding.

    Args:
        finding_id: UUID string of the finding to waive.
        reason_code: Approved waiver reason code.
        justification: Free-text justification (min 10 chars).

    Returns:
        DqFindingResponse dict for the new waiver row.
    """
    return _safe_post(
        f"{_get_base_url()}/api/v1/dq-findings/waiver/{finding_id}",
        body={"reason_code": reason_code, "justification": justification},
    )


def post_correction(
    supersedes_id: str,
    new_record: dict[str, Any],
    reason_code: str,
    justification: str,
) -> dict[str, Any]:
    """Post an emission correction (FR-21).

    esg_manager role only.  Called from Drill-down page.

    Args:
        supersedes_id: UUID string of the emission row to supersede.
        new_record: EmissionCreate payload dict.
        reason_code: Approved correction reason code.
        justification: Free-text justification.

    Returns:
        EmissionCorrectionResponse dict.
    """
    return _safe_post(
        f"{_get_base_url()}/api/v1/emissions/correction",
        body={
            "supersedes_id": supersedes_id,
            "new_record": new_record,
            "reason_code": reason_code,
            "justification": justification,
        },
    )


def trigger_pdf_report(anno: int, gwp_set: str = "AR6", language: str = "it") -> dict[str, Any]:
    """POST to /api/v1/reports/pdf; returns {job_id, status}.

    Args:
        anno: Reporting year.
        gwp_set: GWP set.
        language: Report language.

    Returns:
        ReportJobStatus dict.
    """
    return _safe_post(
        f"{_get_base_url()}/api/v1/reports/pdf",
        body={"anno": anno, "gwp_set": gwp_set, "language": language},
    )


def trigger_excel_report(anno: int, gwp_set: str = "AR6") -> dict[str, Any]:
    """POST to /api/v1/reports/excel; returns {job_id, status}.

    Args:
        anno: Reporting year.
        gwp_set: GWP set.

    Returns:
        ReportJobStatus dict.
    """
    return _safe_post(
        f"{_get_base_url()}/api/v1/reports/excel",
        body={"anno": anno, "gwp_set": gwp_set},
    )


@st.cache_data(ttl=300, show_spinner=False)
def fetch_intensity(
    tenant_id: str,
    denominator_type: str,
    anno_from: int | None = None,
    anno_to: int | None = None,
    codice_sito: str | None = None,
    gwp_set: str = "AR6",
) -> dict[str, Any]:
    """Fetch intensity metrics from ``GET /api/v1/intensity``.

    Args:
        tenant_id: Tenant UUID string.
        denominator_type: One of 'EUR_revenue', 'm2_production', 'FTE', 'kg_product'.
        anno_from: First reporting year (inclusive).
        anno_to: Last reporting year (inclusive).
        codice_sito: Optional site code filter; omit for multi-site aggregate.
        gwp_set: GWP characterisation set (default 'AR6').

    Returns:
        IntensityResponse JSON dict.  Returns empty dict on network/auth error.
    """
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "denominator_type": denominator_type,
        "gwp_set": gwp_set,
    }
    if anno_from is not None:
        params["anno_from"] = anno_from
    if anno_to is not None:
        params["anno_to"] = anno_to
    if codice_sito:
        params["codice_sito"] = codice_sito
    return _safe_get(f"{_get_base_url()}/api/v1/intensity/", params=params)


def fetch_job_status(job_id: str) -> dict[str, Any]:
    """Poll job status from ``GET /api/v1/reports/status/{job_id}``.

    Args:
        job_id: UUID string of the report job.

    Returns:
        ReportJobStatus dict.
    """
    return _safe_get(f"{_get_base_url()}/api/v1/reports/status/{job_id}")


def emissions_to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert a list of EmissionResponse dicts to a pandas DataFrame.

    Args:
        rows: List returned by ``fetch_emissions``.

    Returns:
        DataFrame with typed columns; empty DataFrame if rows is empty.
    """
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # Ensure numeric columns are float
    for col in ("tco2e", "co2_tonne", "ch4_tco2e", "n2o_tco2e",
                "co2_biogenic_tonne", "co2_fossil_tonne"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

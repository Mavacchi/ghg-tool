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
  POST /api/v1/exports/pdf        (REV-WAVE3-002: was /api/v1/reports/pdf)
  POST /api/v1/exports/xlsx       (REV-WAVE3-002: was /api/v1/reports/excel)
  GET  /api/v1/exports/jobs/{id}  (REV-WAVE3-002: was /api/v1/reports/status/{id})
  GET  /api/v1/exports/jobs/{id}/download
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd
import streamlit as st

from ghg_tool.ui.clients._http_client import safe_request as _safe_request

_DEFAULT_BASE_URL = os.environ.get("GHG_API_BASE_URL", "http://localhost:8000")
_TIMEOUT = 30.0


def _get_base_url() -> str:
    return st.session_state.get("api_base_url", _DEFAULT_BASE_URL)


def _get_headers() -> dict[str, str]:
    """Build the request headers, fail-closed when no token is available.

    When no token is in session_state and demo mode is disabled, the
    Authorization header is OMITTED entirely (rather than sent as an empty
    bearer). An empty-bearer header would let auth middleware that
    special-cases the "missing header" branch silently accept the request,
    and the trailing space in ``"Bearer "`` is itself a parser ambiguity.
    """
    from ghg_tool.ui.streamlit_app.lib.auth import _DEMO_MODE, _DEMO_TOKEN

    token = st.session_state.get("token")
    if not token:
        token = _DEMO_TOKEN if _DEMO_MODE else None
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _safe_get(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Perform a GET request with auth; return parsed JSON or empty dict on error.

    Args:
        url: Full URL to request.
        params: Optional query parameters.

    Returns:
        Parsed JSON response or empty dict on network/auth error.
    """
    result = _safe_request("GET", url, headers=_get_headers(), params=params, timeout=_TIMEOUT, _httpx=httpx)
    # api_client contract: return {} (not an error dict) on any failure, for backward compat.
    if "error" in result:
        return {}
    return result


def _safe_post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    """Perform a POST request with auth; return parsed JSON or error dict.

    Args:
        url: Full URL to request.
        body: JSON-serialisable request body.

    Returns:
        Parsed JSON response or ``{"error": "..."}`` on failure.
    """
    return _safe_request("POST", url, headers=_get_headers(), body=body, timeout=_TIMEOUT, _httpx=httpx)


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


def create_emission(payload: dict[str, Any]) -> dict[str, Any]:
    """POST a new emission row to /api/v1/emissions (data_steward role).

    Args:
        payload: ``EmissionCreate`` dict (must include all mandatory
            provenance fields; server fills id, calc_timestamp, etc.).

    Returns:
        ``EmissionCreateResponse`` dict with ``id``, ``correlation_id``,
        ``created_at`` on success, or ``{"error": "...", "status_code": ...}``.
    """
    return _safe_post(f"{_get_base_url()}/api/v1/emissions/", body=payload)


def list_users() -> list[dict[str, Any]] | dict[str, Any]:
    """GET /api/v1/users (esg_manager only).

    Returns the list of users in the caller's tenant. Password hashes are
    never returned by the server. On HTTP error the wrapper returns the
    usual ``{"error": "...", "status_code": ...}`` shape.
    """
    raw = _safe_get(f"{_get_base_url()}/api/v1/users/")
    return raw if isinstance(raw, list) else raw  # type: ignore[return-value]


def create_user(
    *,
    username: str,
    email: str,
    role_code: str,
    password: str,
) -> dict[str, Any]:
    """POST /api/v1/users (esg_manager only).

    Body fields are validated server-side; the plaintext password is
    bcrypt-hashed before persistence and never logged. Common HTTP errors:
    409 (duplicate username/email), 422 (invalid role / bad email),
    403 (caller is not esg_manager).
    """
    return _safe_post(
        f"{_get_base_url()}/api/v1/users/",
        body={
            "username": username,
            "email": email,
            "role_code": role_code,
            "password": password,
        },
    )


def publish_factor(
    factor_uuid: str,
    reason_code: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """POST to /api/v1/factor-catalog/{uuid}/publish (esg_manager only).

    Flips the draft factor's ``is_published`` flag to True via a
    race-safe conditional UPDATE, stamps ``published_at`` and
    ``published_by``, and writes an ``calc.audit_log`` row in the same
    transaction. After the call the row is frozen by the DB trigger
    ``trg_factor_immutability`` (MG-02).

    Args:
        factor_uuid: UUID of the draft factor to publish.
        reason_code: One of INITIAL_PUBLICATION / VERSION_BUMP /
            METHODOLOGY_UPDATE / SOURCE_REVISION / CORRECTION_REPLACEMENT.
        notes: Optional ``publish_notes`` (max 2000 chars).

    Returns:
        Updated ``FactorCatalogPublishResponse`` dict, or
        ``{"error": "...", "status_code": ...}`` on failure.
    """
    body: dict[str, Any] = {"reason_code": reason_code}
    if notes:
        body["publish_notes"] = notes
    return _safe_post(
        f"{_get_base_url()}/api/v1/factor-catalog/{factor_uuid}/publish",
        body=body,
    )


def create_factor(payload: dict[str, Any]) -> dict[str, Any]:
    """POST a new factor version to /api/v1/factor-catalog (data_steward).

    Forces ``is_published=False`` client-side: only the publish workflow
    (not yet implemented) may flip that flag, and once flipped the DB
    trigger MG-02 freezes the row.

    Args:
        payload: ``FactorCatalogCreate`` dict.

    Returns:
        Created ``FactorCatalogResponse`` dict, or error dict.
    """
    payload = {**payload, "is_published": False}
    return _safe_post(f"{_get_base_url()}/api/v1/factor-catalog/", body=payload)


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
    """POST to /api/v1/exports/pdf; returns {job_id, status}.

    REV-WAVE3-002: previously pointed at the legacy /api/v1/reports/pdf stub
    which uses create_report_job() and does NOT invoke PDFBuilder.  Now targets
    the functional exports router which triggers the full WeasyPrint pipeline.

    Args:
        anno: Reporting year.
        gwp_set: GWP set.
        language: Report language.

    Returns:
        ReportJobStatus dict.
    """
    return _safe_post(
        f"{_get_base_url()}/api/v1/exports/pdf",
        body={"anno": anno, "gwp_set": gwp_set, "language": language},
    )


def trigger_excel_report(anno: int, gwp_set: str = "AR6") -> dict[str, Any]:
    """POST to /api/v1/exports/xlsx; returns {job_id, status}.

    REV-WAVE3-002: previously pointed at the legacy /api/v1/reports/excel stub.
    Now targets the functional exports router which triggers XlsxBuilder.

    Args:
        anno: Reporting year.
        gwp_set: GWP set.

    Returns:
        ReportJobStatus dict.
    """
    return _safe_post(
        f"{_get_base_url()}/api/v1/exports/xlsx",
        body={"anno": anno, "gwp_set": gwp_set},
    )


@st.cache_data(ttl=300, show_spinner=False)
def fetch_intensity(
    denominator_type: str,
    anno_from: int | None = None,
    anno_to: int | None = None,
    codice_sito: str | None = None,
    gwp_set: str = "AR6",
) -> dict[str, Any]:
    """Fetch intensity metrics from ``GET /api/v1/intensity``.

    SEC-P0-003: ``tenant_id`` is no longer accepted as a parameter.
    The backend sources tenant isolation exclusively from the JWT claim.
    Passing ``tenant_id`` in the query string would be silently ignored
    by the server — this client no longer sends it.

    Args:
        denominator_type: One of 'EUR_revenue', 'm2_production', 'FTE', 'kg_product'.
        anno_from: First reporting year (inclusive).
        anno_to: Last reporting year (inclusive).
        codice_sito: Optional site code filter; omit for multi-site aggregate.
        gwp_set: GWP characterisation set (default 'AR6').

    Returns:
        IntensityResponse JSON dict.  Returns empty dict on network/auth error.
    """
    params: dict[str, Any] = {
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
    """Poll job status from ``GET /api/v1/exports/jobs/{job_id}``.

    REV-WAVE3-002: previously polled /api/v1/reports/status/{job_id} (legacy
    stub).  Now targets the exports router which returns the canonical wire
    status (PENDING | RUNNING | COMPLETED | FAILED).

    Args:
        job_id: UUID string of the report job.

    Returns:
        ReportJobStatus dict.
    """
    return _safe_get(f"{_get_base_url()}/api/v1/exports/jobs/{job_id}")


def download_report(job_id: str) -> bytes | None:
    """Download binary document bytes from a completed export job.

    REV-WAVE3-002: new function targeting GET /api/v1/exports/jobs/{job_id}/download.
    Returns the raw PDF or XLSX bytes, or None on error.

    Args:
        job_id: UUID string of the completed report job.

    Returns:
        PDF or XLSX bytes, or None on network/auth error or job not yet done.
    """
    try:
        resp = httpx.get(
            f"{_get_base_url()}/api/v1/exports/jobs/{job_id}/download",
            headers=_get_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.content
    except (httpx.HTTPStatusError, httpx.RequestError):
        return None


def fetch_excel_template(*, token: str | None = None) -> bytes | None:
    """Scarica il template Excel vuoto da GET /api/v1/raw/excel/template.

    Chiama l'endpoint che genera il workbook .xlsx con i 3 fogli scope +
    il foglio _README con istruzioni. Il file restituito può essere
    passato direttamente a ``st.download_button``.

    Args:
        token: Bearer JWT per la sessione corrente. Se None usa il token
            da ``st.session_state`` (o il token demo se in modalità demo).

    Returns:
        Bytes del file .xlsx, oppure None in caso di errore di rete o auth.
    """
    from ghg_tool.ui.streamlit_app.lib.auth import _DEMO_MODE, _DEMO_TOKEN  # noqa: PLC0415

    if not token:
        token = st.session_state.get("token")
    if not token:
        token = _DEMO_TOKEN if _DEMO_MODE else None

    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = httpx.get(
            f"{_get_base_url()}/api/v1/raw/excel/template",
            headers=headers,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.content
    except (httpx.HTTPStatusError, httpx.RequestError):
        return None


def import_excel(file_bytes: bytes) -> dict[str, Any]:
    """POST an Excel workbook to /api/v1/raw/excel/import.

    The bytes are sent as multipart/form-data under the field name
    ``workbook`` with the OOXML content-type.  The server performs all
    parsing, DQ-CRIT validation, and DB insertion; this helper is a thin
    transport wrapper.

    Args:
        file_bytes: Raw .xlsx bytes from a Streamlit file_uploader.

    Returns:
        On success: ExcelImportResponse dict with keys
        ``batch_id``, ``scope1_rows``, ``scope2_rows``, ``scope3_rows``,
        ``dq_findings``, ``blocked``.
        On failure: ``{"error": "...", "status_code": int}``.
    """
    from ghg_tool.ui.streamlit_app.lib.auth import _DEMO_MODE, _DEMO_TOKEN  # noqa: PLC0415

    token = st.session_state.get("token")
    if not token:
        token = _DEMO_TOKEN if _DEMO_MODE else None

    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = httpx.post(
            f"{_get_base_url()}/api/v1/raw/excel/import",
            headers=headers,
            files={
                "workbook": (
                    "upload.xlsx",
                    file_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            timeout=120.0,  # large uploads may take longer than the default 30 s
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json()
        except Exception:  # noqa: BLE001
            detail = exc.response.text
        return {
            "error": detail,
            "status_code": exc.response.status_code,
        }
    except httpx.RequestError as exc:
        return {"error": str(exc)}


class AutoCalcError(Exception):
    """Raised by ``calc_preview`` and ``calc_insert`` on typed API errors.

    Attributes:
        detail: Human-readable error message extracted from the API response.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def calc_preview(payload: dict[str, Any], *, token: str) -> dict[str, Any]:
    """POST to ``/api/v1/calc/preview`` — compute tCO2e without DB write.

    The endpoint is read-only (no row is persisted).  Safe to call
    repeatedly as the user edits the form.  ``quantita`` MUST be sent as a
    string to preserve ``Decimal`` precision (§9 of the auto-calc design).

    Args:
        payload: ``CalcInputRequest`` dict — keys include ``scope``,
            ``sub_scope``, ``codice_sito``, ``anno``, ``quantita`` (str),
            ``unita``, ``gwp_set``, and optional scope-specific fields
            (``combustibile``, ``strumento_mb``, ``sottocategoria``, etc.).
        token: Bearer JWT for the current session (editor or admin role).

    Returns:
        ``CalcPreviewResponse`` dict on HTTP 200, containing ``tco2e``,
        ``breakdown``, ``factor_metadata``, ``gwp_set``, ``methodology``,
        ``disclosure_notes``, and ``dq_findings``.

    Raises:
        AutoCalcError: On HTTP 422 (validation / missing factor), 403
            (insufficient role), or network-level errors.
    """
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    try:
        resp = httpx.post(
            f"{_get_base_url()}/api/v1/calc/preview",
            headers=headers,
            json=payload,
            timeout=_TIMEOUT,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        # Extract detail from response body (problem+json or FastAPI format).
        try:
            body = resp.json()
            detail = body.get("detail", str(body))
            if isinstance(detail, list):
                # FastAPI validation errors return a list of dicts.
                detail = "; ".join(
                    str(e.get("msg", e)) for e in detail
                )
        except Exception:  # noqa: BLE001
            detail = resp.text or f"HTTP {resp.status_code}"
        if resp.status_code == 403:
            raise AutoCalcError("Ruolo insufficiente: solo editor/admin")
        raise AutoCalcError(str(detail))
    except AutoCalcError:
        raise
    except httpx.RequestError as exc:
        raise AutoCalcError(f"Errore di rete: backend non raggiungibile — {exc}") from exc


def calc_insert(payload: dict[str, Any], *, token: str) -> dict[str, Any]:
    """POST to ``/api/v1/calc/insert`` — compute tCO2e and write one ledger row.

    Identical request body to :func:`calc_preview`.  On success the backend
    returns the preview payload **plus** ``emission_id`` (UUID of the new
    ``calc.emissions_consolidated`` row) and ``audit_log_id``.

    This path is guarded by the append-only ledger trigger.  Never call it
    twice with the same payload: use the optional ``idempotency_key`` field
    in the payload to de-dup network retries.

    Args:
        payload: ``CalcInputRequest`` dict — same shape as for
            :func:`calc_preview`, with an optional ``idempotency_key``
            (UUID string) for retry safety.
        token: Bearer JWT (editor or admin role required).

    Returns:
        ``CalcInsertResponse`` dict on HTTP 201 — preview body plus
        ``emission_id`` and ``audit_log_id``.

    Raises:
        AutoCalcError: On HTTP 422 (validation / DQ failure), 403
            (insufficient role), 409 (duplicate active row — caller must
            use the FR-21 correction workflow), or network errors.
    """
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    try:
        resp = httpx.post(
            f"{_get_base_url()}/api/v1/calc/insert",
            headers=headers,
            json=payload,
            timeout=_TIMEOUT,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        try:
            body = resp.json()
            detail = body.get("detail", str(body))
            if isinstance(detail, list):
                detail = "; ".join(
                    str(e.get("msg", e)) for e in detail
                )
        except Exception:  # noqa: BLE001
            detail = resp.text or f"HTTP {resp.status_code}"
        if resp.status_code == 403:
            raise AutoCalcError("Ruolo insufficiente: solo editor/admin")
        raise AutoCalcError(str(detail))
    except AutoCalcError:
        raise
    except httpx.RequestError as exc:
        raise AutoCalcError(f"Errore di rete: backend non raggiungibile — {exc}") from exc


class FactorCRUDError(Exception):
    """Raised when a factor CRUD operation fails with a typed HTTP error.

    Attributes:
        status_code: HTTP status code returned by the server (422, 404, 403, …).
        detail: Human-readable error message from the API ``problem+json`` body.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class EmissionCorrectionError(Exception):
    """Raised when ``correct_emission`` receives a non-201 response.

    Attributes:
        status_code: HTTP status code (422, 404, 403, …).
        detail: Human-readable error detail from the API response body.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def patch_factor_draft(
    factor_uuid: str,
    updates: dict[str, Any],
    *,
    token: str,
) -> dict[str, Any]:
    """PATCH ``/api/v1/factor-catalog/{uuid}`` to edit a DRAFT factor.

    Only DRAFT factors (``is_published=False``) can be edited.  The server
    returns 422 when called on a published row (frozen by DB trigger MG-02).

    Args:
        factor_uuid: UUID of the draft factor to update.
        updates: Partial ``FactorCatalogUpdate`` payload dict.
        token: Bearer JWT for the current session (data_steward role required).

    Returns:
        Updated ``FactorCatalogResponse`` dict on success (HTTP 200).

    Raises:
        FactorCRUDError: On HTTP 422 (published row), 404 (not found), or
            403 (forbidden / wrong role).
    """
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    try:
        resp = httpx.patch(
            f"{_get_base_url()}/api/v1/factor-catalog/{factor_uuid}",
            headers=headers,
            json=updates,
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json()
        # Extract detail from problem+json if present
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:  # noqa: BLE001
            detail = resp.text
        raise FactorCRUDError(status_code=resp.status_code, detail=str(detail))
    except FactorCRUDError:
        raise
    except httpx.RequestError as exc:
        raise FactorCRUDError(status_code=0, detail=str(exc)) from exc


def delete_factor_draft(
    factor_uuid: str,
    *,
    token: str,
) -> None:
    """DELETE ``/api/v1/factor-catalog/{uuid}`` to remove a DRAFT factor.

    Only DRAFT factors can be deleted.  Published factors are immutable and
    return 422.

    Args:
        factor_uuid: UUID of the draft factor to delete.
        token: Bearer JWT for the current session (data_steward role required).

    Returns:
        None on HTTP 204 (success — no content).

    Raises:
        FactorCRUDError: On HTTP 422 (published row), 404 (not found), or
            403 (forbidden / wrong role).
    """
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
    }
    try:
        resp = httpx.delete(
            f"{_get_base_url()}/api/v1/factor-catalog/{factor_uuid}",
            headers=headers,
            timeout=_TIMEOUT,
        )
        if resp.status_code == 204:
            return None
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:  # noqa: BLE001
            detail = resp.text
        raise FactorCRUDError(status_code=resp.status_code, detail=str(detail))
    except FactorCRUDError:
        raise
    except httpx.RequestError as exc:
        raise FactorCRUDError(status_code=0, detail=str(exc)) from exc


def correct_emission(
    emission_id: str,
    payload: dict[str, Any],
    *,
    token: str,
) -> dict[str, Any]:
    """POST ``/api/v1/emissions/{id}/correct`` — append-only correction.

    Creates a new emission row and links the original via ``superseded_by``.
    The original row is NEVER overwritten (audit immutability).

    Args:
        emission_id: UUID of the emission row to supersede.
        payload: ``EmissionCorrectionRequest`` dict with keys
            ``reason_code``, ``tco2e_corrected``, and ``notes``.
        token: Bearer JWT for the current session (data_steward role required).

    Returns:
        ``EmissionCorrectionResponse`` dict on HTTP 201 (new row created).

    Raises:
        EmissionCorrectionError: On HTTP 422 (validation), 404 (not found),
            or 403 (forbidden / wrong role).
    """
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    try:
        resp = httpx.post(
            f"{_get_base_url()}/api/v1/emissions/{emission_id}/correct",
            headers=headers,
            json=payload,
            timeout=_TIMEOUT,
        )
        if resp.status_code == 201:
            return resp.json()
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:  # noqa: BLE001
            detail = resp.text
        raise EmissionCorrectionError(status_code=resp.status_code, detail=str(detail))
    except EmissionCorrectionError:
        raise
    except httpx.RequestError as exc:
        raise EmissionCorrectionError(status_code=0, detail=str(exc)) from exc


def _safe_patch(url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Perform a PATCH request with auth; return parsed JSON or error dict.

    Args:
        url: Full URL to request.
        body: Optional JSON-serialisable request body.

    Returns:
        Parsed JSON response or ``{"error": "...", "status_code": int}`` on failure.
    """
    try:
        resp = httpx.patch(
            url,
            headers=_get_headers(),
            json=body if body is not None else {},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        return {"error": str(exc), "status_code": exc.response.status_code}
    except httpx.RequestError as exc:
        return {"error": str(exc)}


def list_chart_annotations(
    chart_key: str,
    anchor_year: int | None = None,
    include_hidden: bool = False,
) -> list[dict[str, Any]]:
    """Fetch visible chart annotations from GET /api/v1/chart-annotations.

    Args:
        chart_key: Logical chart identifier (required by the API).
        anchor_year: Optional year filter; omit to retrieve all years.
        include_hidden: When True, request hidden annotations (requires
            esg_manager or auditor role server-side).

    Returns:
        List of annotation dicts, or empty list on network/auth error.
    """
    params: dict[str, Any] = {"chart_key": chart_key}
    if anchor_year is not None:
        params["anchor_year"] = anchor_year
    if include_hidden:
        params["include_hidden"] = "true"
    raw = _safe_get(f"{_get_base_url()}/api/v1/chart-annotations/", params=params)
    # API returns a JSON array directly (not wrapped in a key).
    if isinstance(raw, list):
        return raw
    return []


def create_chart_annotation(
    chart_key: str,
    title: str,
    body: str,
    severity: str = "INFO",
    anchor_year: int | None = None,
    anchor_label: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST a new annotation to /api/v1/chart-annotations.

    Args:
        chart_key: Logical chart identifier (e.g. 'drilldown_scope').
        title: Short annotation title (max 120 chars).
        body: Full narrative text (max 2000 chars).
        severity: INFO, WARNING, or CRITICAL (default INFO).
        anchor_year: Optional year the annotation is attached to.
        anchor_label: Optional free-text label for the anchor.
        extra: Optional freeform JSON metadata.

    Returns:
        The created annotation dict on success, or
        ``{"error": "...", "status_code": int}`` on failure.
    """
    payload: dict[str, Any] = {
        "chart_key": chart_key,
        "title": title,
        "body": body,
        "severity": severity,
    }
    if anchor_year is not None:
        payload["anchor_year"] = anchor_year
    if anchor_label is not None:
        payload["anchor_label"] = anchor_label
    if extra is not None:
        payload["extra"] = extra
    return _safe_post(f"{_get_base_url()}/api/v1/chart-annotations/", body=payload)


def toggle_annotation_visibility(
    annotation_id: str,
    is_visible: bool,
) -> dict[str, Any]:
    """PATCH the visibility flag of a chart annotation.

    Args:
        annotation_id: UUID string of the annotation to update.
        is_visible: New visibility value.

    Returns:
        The updated annotation dict on success, or
        ``{"error": "...", "status_code": int}`` on failure.
    """
    return _safe_patch(
        f"{_get_base_url()}/api/v1/chart-annotations/{annotation_id}/visibility",
        body={"is_visible": is_visible},
    )


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

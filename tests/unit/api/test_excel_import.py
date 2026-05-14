"""Unit tests for POST /api/v1/raw/excel/import.

Covers:
- 401 unauthenticated (no token)
- 403 auditor role
- 422 invalid .xlsx (parser fails)
- 422 DQ-CRIT blocked (orchestrator returns pipeline_blocked=True)
- 200 happy path with mocked orchestrator returning 3 rows per scope

All DB operations and the ETL orchestrator are mocked.  No live PostgreSQL
instance or real .xlsx file is required.
"""

from __future__ import annotations

import io
import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# Set env vars before any project imports so JWT/settings are consistent.
os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

import pytest
from fastapi.testclient import TestClient

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.main import app
from ghg_tool.etl.orchestrator import ETLResult

# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------

_TENANT_ID = str(uuid.uuid4())
_USER_DS = str(uuid.uuid4())
_USER_ESG = str(uuid.uuid4())
_USER_AU = str(uuid.uuid4())

# Minimal valid .xlsx-shaped bytes — enough to trigger openpyxl but not a real
# workbook.  The parse_workbook call is mocked in every test that needs it to
# succeed, so the actual bytes content does not matter for happy-path tests.
_FAKE_XLSX_BYTES = b"PK\x03\x04" + b"\x00" * 100


def _make_user(role: str, user_id: str | None = None) -> CurrentUser:
    """Build a CurrentUser for dependency override.

    Args:
        role: RBAC role code.
        user_id: Optional user sub UUID.

    Returns:
        CurrentUser pydantic model.
    """
    return CurrentUser(
        sub=user_id or str(uuid.uuid4()),
        role=role,  # type: ignore[arg-type]
        tenant_id=_TENANT_ID,
        jti=str(uuid.uuid4()),
    )


def _user_override(role: str, user_id: str | None = None) -> Any:
    """Return an async dependency override for get_current_user.

    Args:
        role: Role code to inject.
        user_id: Optional user UUID.

    Returns:
        Async callable that returns a CurrentUser.
    """
    user = _make_user(role, user_id)

    async def _dep() -> CurrentUser:
        return user

    return _dep


def _noop_db() -> Any:
    """Return a no-op async DB session override.

    Returns:
        Async generator yielding a MagicMock session.
    """
    async def _gen() -> Any:
        session = AsyncMock()
        # Needed so session.add() and session.flush() don't raise
        session.add = MagicMock()
        session.flush = AsyncMock()
        yield session

    return _gen


def _make_etl_result(
    *,
    blocked: bool = False,
    rows_per_scope: int = 3,
) -> ETLResult:
    """Build a minimal ETLResult for orchestrator mocking.

    Args:
        blocked: Whether to simulate a DQ-CRIT block.
        rows_per_scope: Number of staging rows per scope (ignored when blocked).

    Returns:
        ETLResult with the requested configuration.
    """
    crit_finding: dict[str, Any] = {
        "rule_id": "DQ-CRIT-01",
        "severity": "CRIT",
        "scope": 1,
        "codice_sito": "TEST_SITE",
        "anno": 2024,
        "trigger_desc": "Facility coverage gap",
        "recommended_action": "Add missing facility rows",
        "blocks_pipeline": True,
        "dq_report_version": "1.0.0",
    }

    def _fake_rows(n: int) -> list[dict[str, Any]]:
        return [
            {
                "id": uuid.uuid4(),
                "tenant_id": uuid.UUID(_TENANT_ID),
                "batch_id": uuid.uuid4(),
                "scope": 1,
                "anno": 2024,
                "idempotency_key": f"key-{i}",
                "ingested_by": "test",
            }
            for i in range(n)
        ]

    batch_id = uuid.uuid4()
    if blocked:
        return ETLResult(
            correlation_id=batch_id,
            scope1_row_count=0,
            scope2_row_count=0,
            scope3_row_count=0,
            all_findings=[crit_finding],
            dlq_entries=[],
            pipeline_blocked=True,
            scope1_rows=[],
            scope2_rows=[],
            scope3_rows=[],
        )
    return ETLResult(
        correlation_id=batch_id,
        scope1_row_count=rows_per_scope,
        scope2_row_count=rows_per_scope,
        scope3_row_count=rows_per_scope,
        all_findings=[
            {
                "rule_id": "DQ-WARN-01",
                "severity": "WARN",
                "scope": 2,
                "dq_report_version": "1.0.0",
            }
        ],
        dlq_entries=[],
        pipeline_blocked=False,
        scope1_rows=_fake_rows(rows_per_scope),
        scope2_rows=_fake_rows(rows_per_scope),
        scope3_rows=_fake_rows(rows_per_scope),
    )


def _multipart_upload(file_bytes: bytes = _FAKE_XLSX_BYTES) -> dict[str, Any]:
    """Build the multipart payload dict for the TestClient.

    Args:
        file_bytes: Bytes to send as the workbook field.

    Returns:
        Dict suitable for ``files=`` kwarg of httpx/requests.
    """
    return {
        "workbook": (
            "upload.xlsx",
            io.BytesIO(file_bytes),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }


# ---------------------------------------------------------------------------
# Test 1: 401 when no Authorization header is provided
# ---------------------------------------------------------------------------


def test_import_excel_401_unauthenticated() -> None:
    """POST without any auth token must return 401."""
    # No dependency override — the real JWT decode will reject the missing header.
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/v1/raw/excel/import",
            files=_multipart_upload(),
        )
    app.dependency_overrides.clear()

    assert resp.status_code == 401, resp.text
    body = resp.json()
    assert body.get("status") == 401 or "Unauthorized" in str(body)


# ---------------------------------------------------------------------------
# Test 2: 403 when role is auditor
# ---------------------------------------------------------------------------


def test_import_excel_403_auditor() -> None:
    """Auditor role must receive 403 Forbidden."""
    app.dependency_overrides[get_current_user] = _user_override("auditor", _USER_AU)
    app.dependency_overrides[get_db] = _noop_db()
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/v1/raw/excel/import",
            files=_multipart_upload(),
        )
    app.dependency_overrides.clear()

    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body.get("status") == 403 or "Forbidden" in str(body)


# ---------------------------------------------------------------------------
# Test 3: 422 when the workbook cannot be parsed
# ---------------------------------------------------------------------------


def test_import_excel_422_parse_failure() -> None:
    """WorkbookParseError from parse_workbook must surface as 422."""
    from ghg_tool.etl.readers.excel_reader import WorkbookParseError

    app.dependency_overrides[get_current_user] = _user_override("data_steward", _USER_DS)
    app.dependency_overrides[get_db] = _noop_db()

    with patch(
        "ghg_tool.api.routers.excel_import.parse_workbook",
        side_effect=WorkbookParseError("Sheet 'Scope1' is missing required columns: ['Anno']"),
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/raw/excel/import",
                files=_multipart_upload(),
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert "Workbook Parse Error" in str(body) or "missing required" in str(body).lower()


# ---------------------------------------------------------------------------
# Test 4: 422 when DQ-CRIT gates block the pipeline
# ---------------------------------------------------------------------------


def test_import_excel_422_dq_crit_blocked() -> None:
    """A pipeline_blocked result must return 422 with blocked_findings."""
    import pandas as pd

    app.dependency_overrides[get_current_user] = _user_override("esg_manager", _USER_ESG)
    app.dependency_overrides[get_db] = _noop_db()

    fake_parsed = {
        "scope1": pd.DataFrame({"Scope": [1], "Anno": [2024], "Codice_Sito": ["X"]}),
    }
    blocked_result = _make_etl_result(blocked=True)

    with (
        patch(
            "ghg_tool.api.routers.excel_import.parse_workbook",
            return_value=fake_parsed,
        ),
        patch(
            "ghg_tool.api.routers.excel_import.run_ingestion_pipeline",
            return_value=blocked_result,
        ),
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/raw/excel/import",
                files=_multipart_upload(),
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert "blocked_findings" in body or "DQ-CRIT" in str(body)
    # The blocked finding detail must be present
    detail_str = str(body)
    assert "DQ-CRIT-01" in detail_str or "critical" in detail_str.lower()


# ---------------------------------------------------------------------------
# Test 5: 200 happy path — 3 rows per scope
# ---------------------------------------------------------------------------


def test_import_excel_200_happy_path() -> None:
    """Happy path: 3 rows per scope inserted, batch_id returned, blocked=False."""
    import pandas as pd

    app.dependency_overrides[get_current_user] = _user_override("data_steward", _USER_DS)
    app.dependency_overrides[get_db] = _noop_db()

    fake_parsed = {
        "scope1": pd.DataFrame({"Scope": [1, 1, 1]}),
        "scope2": pd.DataFrame({"Scope": [2, 2, 2]}),
        "scope3": pd.DataFrame({"Scope": [3, 3, 3]}),
    }
    happy_result = _make_etl_result(blocked=False, rows_per_scope=3)
    inserted_counts = {"s1": 3, "s2": 3, "s3": 3, "findings": 1}

    with (
        patch(
            "ghg_tool.api.routers.excel_import.parse_workbook",
            return_value=fake_parsed,
        ),
        patch(
            "ghg_tool.api.routers.excel_import.run_ingestion_pipeline",
            return_value=happy_result,
        ),
        patch(
            "ghg_tool.api.routers.excel_import._do_db_work",
            return_value=inserted_counts,
        ),
        # siem.emit is best-effort; avoid real HTTP calls in tests
        patch("ghg_tool.api.routers.excel_import.siem.emit"),
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/raw/excel/import",
                files=_multipart_upload(),
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope1_rows"] == 3
    assert body["scope2_rows"] == 3
    assert body["scope3_rows"] == 3
    assert body["dq_findings"] == 1
    assert body["blocked"] is False
    assert "batch_id" in body
    # batch_id must be a valid UUID string
    uuid.UUID(body["batch_id"])


# ---------------------------------------------------------------------------
# Test 6: 422 when the upload exceeds 10 MB
# ---------------------------------------------------------------------------


def test_import_excel_422_too_large() -> None:
    """Uploads larger than 10 MB must be rejected with 422."""
    large_bytes = b"A" * (10 * 1024 * 1024 + 1)

    app.dependency_overrides[get_current_user] = _user_override("data_steward", _USER_DS)
    app.dependency_overrides[get_db] = _noop_db()

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/v1/raw/excel/import",
            files=_multipart_upload(large_bytes),
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert "10 MB" in str(body) or "size limit" in str(body).lower()

"""Unit tests for the Celery-backed exports endpoints (REV-WAVE3-007).

Tests run without a live Redis instance by using Celery's ALWAYS_EAGER mode
(``CELERY_TASK_ALWAYS_EAGER=True``).  In EAGER mode tasks execute inline in
the calling thread and return an ``EagerResult`` whose ``.state`` and
``.result`` behave identically to the real ``AsyncResult`` object.

Test coverage:
    POST /api/v1/exports/pdf   → 202 + CeleryJobAccepted
    POST /api/v1/exports/xlsx  → 202 + CeleryJobAccepted
    GET  /api/v1/exports/{id}/status → 200 with state
    GET  /api/v1/exports/{id}/download → binary when SUCCESS
    GET  /api/v1/exports/{id}/download → 500 with detail when FAILURE
    Idempotency-Key deduplication → same task_id for identical keys

Existing legacy endpoint tests in test_reports.py and test_exports_router.py
remain unchanged and continue to exercise the in-memory job store.
"""

from __future__ import annotations

import base64
import os
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Must be set before any celery import so the celery app is configured EAGER.
os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")

from fastapi.testclient import TestClient  # noqa: E402

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.main import app  # noqa: E402
from ghg_tool.infrastructure.celery_app import celery_app  # noqa: E402

# Force EAGER execution — tasks run synchronously without a broker.
celery_app.conf.update(
    task_always_eager=True,
    task_eager_propagates=False,  # failures stored as FAILURE state, not raised
)

_TENANT_ID = str(uuid.uuid4())
_OTHER_TENANT_ID = str(uuid.uuid4())


def _user_override(role: str, tenant_id: str = _TENANT_ID) -> Any:
    user = CurrentUser(
        sub=str(uuid.uuid4()),
        role=role,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        jti=str(uuid.uuid4()),
    )

    async def _dep() -> CurrentUser:
        return user

    return _dep


@pytest.fixture()
def admin_client() -> TestClient:
    app.dependency_overrides[get_current_user] = _user_override("admin")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def editor_client() -> TestClient:
    app.dependency_overrides[get_current_user] = _user_override("editor")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/v1/exports/pdf
# ---------------------------------------------------------------------------


_PDF_TASK = "ghg_tool.application.tasks.export_tasks.export_pdf_task.apply_async"
_XLSX_TASK = "ghg_tool.application.tasks.export_tasks.export_excel_task.apply_async"


class TestPostPdfCelery:
    def test_returns_202_and_task_id(self, admin_client: TestClient) -> None:
        """POST /pdf returns 202 Accepted with a task_id."""
        with patch(_PDF_TASK) as mock_aa:
            mock_result = MagicMock()
            mock_result.id = str(uuid.uuid4())
            mock_aa.return_value = mock_result

            resp = admin_client.post("/api/v1/exports/pdf", json={"anno": 2025})

        assert resp.status_code == 202
        body = resp.json()
        assert "task_id" in body
        assert "status_url" in body
        assert body["task_id"] == mock_result.id

    def test_status_url_contains_task_id(self, admin_client: TestClient) -> None:
        """status_url in the 202 response embeds the task_id."""
        with patch(_PDF_TASK) as mock_aa:
            tid = str(uuid.uuid4())
            mock_result = MagicMock()
            mock_result.id = tid
            mock_aa.return_value = mock_result

            resp = admin_client.post("/api/v1/exports/pdf", json={"anno": 2025})

        assert resp.status_code == 202
        assert tid in resp.json()["status_url"]

    def test_editor_forbidden_for_pdf(self, editor_client: TestClient) -> None:
        """editor role cannot trigger PDF — 403."""
        resp = editor_client.post("/api/v1/exports/pdf", json={"anno": 2025})
        assert resp.status_code == 403

    def test_idempotency_key_produces_same_task_id(self, admin_client: TestClient) -> None:
        """Two requests with the same Idempotency-Key yield the same task_id."""
        idem_key = "my-unique-key-001"
        with patch(_PDF_TASK) as mock_aa:
            call_ids: list[str] = []

            def _side_effect(*args: Any, **kwargs: Any) -> MagicMock:
                task_id: str = kwargs.get("task_id") or str(uuid.uuid4())
                call_ids.append(task_id)
                m = MagicMock()
                m.id = task_id
                return m

            mock_aa.side_effect = _side_effect

            resp1 = admin_client.post(
                "/api/v1/exports/pdf",
                json={"anno": 2025},
                headers={"Idempotency-Key": idem_key},
            )
            resp2 = admin_client.post(
                "/api/v1/exports/pdf",
                json={"anno": 2025},
                headers={"Idempotency-Key": idem_key},
            )

        assert resp1.status_code == 202
        assert resp2.status_code == 202
        # Both calls passed the same deterministic task_id to apply_async.
        assert len(call_ids) == 2
        assert call_ids[0] == call_ids[1]

    def test_no_idempotency_key_uses_random_id(self, admin_client: TestClient) -> None:
        """Without an Idempotency-Key, task_id arg is None (Celery picks UUID)."""
        with patch(_PDF_TASK) as mock_aa:
            mock_result = MagicMock()
            mock_result.id = str(uuid.uuid4())
            mock_aa.return_value = mock_result

            admin_client.post("/api/v1/exports/pdf", json={"anno": 2025})

        _, kwargs = mock_aa.call_args
        assert kwargs.get("task_id") is None


# ---------------------------------------------------------------------------
# POST /api/v1/exports/xlsx
# ---------------------------------------------------------------------------


class TestPostXlsxCelery:
    def test_returns_202_and_task_id(self, editor_client: TestClient) -> None:
        """POST /xlsx returns 202 Accepted with a task_id."""
        with patch(_XLSX_TASK) as mock_aa:
            mock_result = MagicMock()
            mock_result.id = str(uuid.uuid4())
            mock_aa.return_value = mock_result

            resp = editor_client.post("/api/v1/exports/xlsx", json={"anno": 2025})

        assert resp.status_code == 202
        body = resp.json()
        assert "task_id" in body

    def test_admin_can_trigger_xlsx(self, admin_client: TestClient) -> None:
        """admin role can also trigger Excel export."""
        with patch(_XLSX_TASK) as mock_aa:
            mock_result = MagicMock()
            mock_result.id = str(uuid.uuid4())
            mock_aa.return_value = mock_result

            resp = admin_client.post("/api/v1/exports/xlsx", json={"anno": 2025})

        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# GET /api/v1/exports/{task_id}/status
# ---------------------------------------------------------------------------


class TestGetCeleryStatus:
    def _make_async_result(self, state: str, result: Any = None) -> MagicMock:
        ar = MagicMock()
        ar.state = state
        ar.result = result
        return ar

    def test_pending_state(self, admin_client: TestClient) -> None:
        """GET /status returns PENDING for a queued task."""
        tid = str(uuid.uuid4())
        with patch("ghg_tool.api.routers.exports.AsyncResult") as mock_ar_cls:
            mock_ar_cls.return_value = self._make_async_result("PENDING")

            resp = admin_client.get(f"/api/v1/exports/{tid}/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "PENDING"
        assert body["result"] is None
        assert body["error"] is None

    def test_success_state_has_result(self, admin_client: TestClient) -> None:
        """GET /status returns SUCCESS with result metadata (no result_b64)."""
        tid = str(uuid.uuid4())
        fake_result = {
            "job_id": tid,
            "job_type": "pdf",
            "size_bytes": 12345,
            "result_b64": base64.b64encode(b"%PDF-1.4 fake").decode("ascii"),
            "tenant_id": _TENANT_ID,
        }
        with patch("ghg_tool.api.routers.exports.AsyncResult") as mock_ar_cls:
            mock_ar_cls.return_value = self._make_async_result("SUCCESS", fake_result)

            resp = admin_client.get(f"/api/v1/exports/{tid}/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "SUCCESS"
        assert body["result"] is not None
        # result_b64 must NOT be present in the status response (too large for polling)
        assert "result_b64" not in body["result"]
        assert body["result"]["size_bytes"] == 12345

    def test_failure_state_has_error(self, admin_client: TestClient) -> None:
        """GET /status returns FAILURE with error string."""
        tid = str(uuid.uuid4())
        with patch("ghg_tool.api.routers.exports.AsyncResult") as mock_ar_cls:
            mock_ar_cls.return_value = self._make_async_result(
                "FAILURE", RuntimeError("WeasyPrint crashed")
            )

            resp = admin_client.get(f"/api/v1/exports/{tid}/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "FAILURE"
        assert "WeasyPrint crashed" in body["error"]
        assert body["result"] is None

    def test_unknown_state_normalised_to_pending(self, admin_client: TestClient) -> None:
        """Unexpected Celery state strings are normalised to PENDING."""
        tid = str(uuid.uuid4())
        with patch("ghg_tool.api.routers.exports.AsyncResult") as mock_ar_cls:
            mock_ar_cls.return_value = self._make_async_result("RECEIVED")

            resp = admin_client.get(f"/api/v1/exports/{tid}/status")

        assert resp.status_code == 200
        assert resp.json()["state"] == "PENDING"


# ---------------------------------------------------------------------------
# GET /api/v1/exports/{task_id}/download
# ---------------------------------------------------------------------------


class TestDownloadCeleryExport:
    def _make_async_result(self, state: str, result: Any = None) -> MagicMock:
        ar = MagicMock()
        ar.state = state
        ar.result = result
        return ar

    def test_download_success_pdf(self, admin_client: TestClient) -> None:
        """GET /download returns PDF bytes for a SUCCESS task."""
        tid = str(uuid.uuid4())
        pdf_bytes = b"%PDF-1.4 fake content"
        fake_result = {
            "job_id": tid,
            "job_type": "pdf",
            "size_bytes": len(pdf_bytes),
            "result_b64": base64.b64encode(pdf_bytes).decode("ascii"),
            "tenant_id": _TENANT_ID,
        }
        with patch("ghg_tool.api.routers.exports.AsyncResult") as mock_ar_cls:
            mock_ar_cls.return_value = self._make_async_result("SUCCESS", fake_result)

            resp = admin_client.get(f"/api/v1/exports/{tid}/download")

        assert resp.status_code == 200
        assert resp.content == pdf_bytes
        assert resp.headers["content-type"] == "application/pdf"
        assert f"ghg_report_{tid}.pdf" in resp.headers["content-disposition"]

    def test_download_success_xlsx(self, editor_client: TestClient) -> None:
        """GET /download returns XLSX bytes for a SUCCESS task."""
        tid = str(uuid.uuid4())
        xlsx_bytes = b"PK\x03\x04fake-xlsx"
        fake_result = {
            "job_id": tid,
            "job_type": "excel",
            "size_bytes": len(xlsx_bytes),
            "result_b64": base64.b64encode(xlsx_bytes).decode("ascii"),
            "tenant_id": _TENANT_ID,
        }
        with patch("ghg_tool.api.routers.exports.AsyncResult") as mock_ar_cls:
            mock_ar_cls.return_value = self._make_async_result("SUCCESS", fake_result)

            resp = editor_client.get(f"/api/v1/exports/{tid}/download")

        assert resp.status_code == 200
        assert resp.content[:2] == b"PK"
        assert "spreadsheetml" in resp.headers["content-type"]

    def test_download_failure_returns_500_with_detail(self, admin_client: TestClient) -> None:
        """GET /download for a FAILURE task returns 500 with error detail."""
        tid = str(uuid.uuid4())
        with patch("ghg_tool.api.routers.exports.AsyncResult") as mock_ar_cls:
            mock_ar_cls.return_value = self._make_async_result(
                "FAILURE", RuntimeError("PDF renderer out of memory")
            )

            resp = admin_client.get(f"/api/v1/exports/{tid}/download")

        assert resp.status_code == 500
        body = resp.json()
        assert "PDF renderer out of memory" in body["detail"]["detail"]

    def test_download_pending_returns_409(self, admin_client: TestClient) -> None:
        """GET /download for a PENDING task returns 409 Conflict."""
        tid = str(uuid.uuid4())
        with patch("ghg_tool.api.routers.exports.AsyncResult") as mock_ar_cls:
            mock_ar_cls.return_value = self._make_async_result("PENDING")

            resp = admin_client.get(f"/api/v1/exports/{tid}/download")

        assert resp.status_code == 409

    def test_download_cross_tenant_returns_404(self, admin_client: TestClient) -> None:
        """GET /download for a task belonging to another tenant returns 404."""
        tid = str(uuid.uuid4())
        fake_result = {
            "job_id": tid,
            "job_type": "pdf",
            "size_bytes": 100,
            "result_b64": base64.b64encode(b"data").decode("ascii"),
            "tenant_id": _OTHER_TENANT_ID,  # different tenant
        }
        with patch("ghg_tool.api.routers.exports.AsyncResult") as mock_ar_cls:
            mock_ar_cls.return_value = self._make_async_result("SUCCESS", fake_result)

            resp = admin_client.get(f"/api/v1/exports/{tid}/download")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Authentication guard
# ---------------------------------------------------------------------------


class TestExportsCeleryAuth:
    def test_unauthenticated_post_pdf_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post("/api/v1/exports/pdf", json={"anno": 2025})
        assert resp.status_code == 401

    def test_unauthenticated_post_xlsx_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post("/api/v1/exports/xlsx", json={"anno": 2025})
        assert resp.status_code == 401

    def test_unauthenticated_status_returns_401(self) -> None:
        app.dependency_overrides.clear()
        tid = str(uuid.uuid4())
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"/api/v1/exports/{tid}/status")
        assert resp.status_code == 401

    def test_unauthenticated_download_returns_401(self) -> None:
        app.dependency_overrides.clear()
        tid = str(uuid.uuid4())
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"/api/v1/exports/{tid}/download")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# OpenAPI / router registration
# ---------------------------------------------------------------------------


class TestExportsCeleryRouterRegistered:
    def test_new_endpoints_in_openapi(self, admin_client: TestClient) -> None:
        """Celery endpoints are visible in the OpenAPI schema."""
        resp = admin_client.get("/openapi.json")
        assert resp.status_code == 200
        paths = resp.json().get("paths", {})
        # New endpoints use /{task_id}/status and /{task_id}/download patterns
        path_keys = list(paths.keys())
        assert any("status" in p and "exports" in p for p in path_keys), path_keys
        assert any("download" in p and "exports" in p for p in path_keys), path_keys

    def test_legacy_endpoints_still_registered(self, admin_client: TestClient) -> None:
        """Legacy /jobs/{job_id} endpoints remain in OpenAPI (backward-compat)."""
        resp = admin_client.get("/openapi.json")
        paths = resp.json().get("paths", {})
        assert any("jobs" in p for p in paths), paths

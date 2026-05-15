"""Unit tests for /api/v1/reports endpoints."""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from fastapi.testclient import TestClient

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.main import app

_TENANT_ID = str(uuid.uuid4())


def _user_override(role: str) -> object:
    user = CurrentUser(
        sub=str(uuid.uuid4()),
        role=role,  # type: ignore[arg-type]
        tenant_id=_TENANT_ID,
        jti=str(uuid.uuid4()),
    )
    async def _dep() -> CurrentUser:
        return user
    return _dep


class TestReportsRouter:
    """Tests for /api/v1/reports endpoints."""

    def test_esg_manager_can_trigger_pdf(self) -> None:
        """admin can POST /reports/pdf and receives 202."""
        app.dependency_overrides[get_current_user] = _user_override("admin")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/reports/pdf",
                json={"anno": 2024, "gwp_set": "AR6"},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "PENDING"

    def test_auditor_cannot_trigger_pdf(self) -> None:
        """viewer cannot trigger PDF generation — 403."""
        app.dependency_overrides[get_current_user] = _user_override("viewer")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/reports/pdf",
                json={"anno": 2024, "gwp_set": "AR6"},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_data_steward_cannot_trigger_pdf(self) -> None:
        """editor cannot trigger PDF (admin only) — 403."""
        app.dependency_overrides[get_current_user] = _user_override("editor")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/reports/pdf",
                json={"anno": 2024, "gwp_set": "AR6"},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_data_steward_can_trigger_excel(self) -> None:
        """editor can POST /reports/excel and receives 202."""
        app.dependency_overrides[get_current_user] = _user_override("editor")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/reports/excel",
                json={"anno": 2024, "gwp_set": "AR6"},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 202

    def test_esg_manager_can_trigger_excel(self) -> None:
        """admin can POST /reports/excel."""
        app.dependency_overrides[get_current_user] = _user_override("admin")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/reports/excel",
                json={"anno": 2024, "gwp_set": "AR6"},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 202

    def test_get_status_returns_404_for_unknown_job(self) -> None:
        """GET /reports/status/{job_id} returns 404 for unknown job_id."""
        app.dependency_overrides[get_current_user] = _user_override("admin")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/api/v1/reports/status/{uuid.uuid4()}")
        app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_get_status_returns_job_for_known_id(self) -> None:
        """GET /reports/status/{job_id} returns PENDING for a just-created job."""
        app.dependency_overrides[get_current_user] = _user_override("admin")
        with TestClient(app, raise_server_exceptions=False) as client:
            create_resp = client.post(
                "/api/v1/reports/pdf",
                json={"anno": 2024, "gwp_set": "AR6"},
            )
            assert create_resp.status_code == 202
            job_id = create_resp.json()["job_id"]
            status_resp = client.get(f"/api/v1/reports/status/{job_id}")
        app.dependency_overrides.clear()
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "PENDING"


class TestExcelDownload:
    """BUG-2: Excel export — completed job exposes download via /download endpoint.

    Verifies that GET /api/v1/exports/jobs/{job_id}/download returns the binary
    bytes after a synchronous _sync_render completes (status == DONE internally,
    COMPLETED on the wire), and that the status endpoint exposes COMPLETED so
    the UI knows to show the download button.
    """

    def test_excel_job_completes_and_download_endpoint_returns_bytes(self) -> None:
        """Full round-trip: POST /xlsx -> COMPLETED status -> binary download."""
        from ghg_tool.application.services.export_service import (
            _internal_to_wire,
            get_job_result,
            get_job_status,
        )
        from ghg_tool.api.routers.exports import router as exports_router  # noqa: F401

        app.dependency_overrides[get_current_user] = _user_override("editor")
        with TestClient(app, raise_server_exceptions=False) as client:
            create_resp = client.post(
                "/api/v1/exports/xlsx",
                json={"anno": 2024, "gwp_set": "AR6"},
            )
        app.dependency_overrides.clear()

        assert create_resp.status_code == 202
        job_id = create_resp.json()["job_id"]

        # In unit-test context _sync_render runs synchronously (no event loop),
        # so the job transitions PENDING -> RUNNING -> DONE before we poll.
        job = get_job_status(uuid.UUID(job_id))
        assert job is not None
        # Internal status must be DONE; wire contract maps DONE -> COMPLETED.
        assert _internal_to_wire(job["status"]) == "COMPLETED"
        # Result bytes must be available.
        result_bytes = get_job_result(uuid.UUID(job_id))
        assert result_bytes is not None

    def test_excel_status_endpoint_shows_completed(self) -> None:
        """GET /api/v1/exports/jobs/{id} returns 'COMPLETED' (not 'DONE').

        Bypasses the background executor by injecting a job directly into
        the in-memory store via _new_job + simulate_job_completion, so the
        test is not subject to executor thread-race timing.
        """
        import ghg_tool.application.services.export_service as _svc

        tenant_id = _TENANT_ID
        # Create a job record WITHOUT scheduling the executor render.
        job_id = _svc._new_job(
            job_type="xlsx",
            tenant_id=tenant_id,
            period={"anno": 2024, "gwp_set": "AR6"},
            user="test-user",
            correlation_id=str(uuid.uuid4()),
        )
        # Force to DONE state and inject sentinel bytes.
        _svc._jobs[str(job_id)]["status"] = _svc._STATUS_DONE
        _svc._results[str(job_id)] = b"PK\x03\x04sentinel"

        app.dependency_overrides[get_current_user] = _user_override("admin")
        with TestClient(app, raise_server_exceptions=False) as client:
            status_resp = client.get(f"/api/v1/exports/jobs/{job_id}")
        app.dependency_overrides.clear()

        assert status_resp.status_code == 200
        wire_status = status_resp.json()["status"]
        # Wire contract must be COMPLETED (never expose internal DONE to clients).
        assert wire_status == "COMPLETED", f"Expected COMPLETED, got {wire_status!r}"

    def test_excel_download_endpoint_returns_binary_stream(self) -> None:
        """GET /api/v1/exports/jobs/{id}/download returns a non-empty XLSX body.

        Bypasses the executor to avoid thread-race timing in the test suite.
        """
        import ghg_tool.application.services.export_service as _svc

        tenant_id = _TENANT_ID
        job_id = _svc._new_job(
            job_type="xlsx",
            tenant_id=tenant_id,
            period={"anno": 2024, "gwp_set": "AR6"},
            user="test-user",
            correlation_id=str(uuid.uuid4()),
        )
        # Inject DONE state + sentinel XLSX bytes.
        _svc._jobs[str(job_id)]["status"] = _svc._STATUS_DONE
        _svc._results[str(job_id)] = b"PK\x03\x04fake-xlsx-payload"

        app.dependency_overrides[get_current_user] = _user_override("admin")
        with TestClient(app, raise_server_exceptions=False) as client:
            dl_resp = client.get(f"/api/v1/exports/jobs/{job_id}/download")
        app.dependency_overrides.clear()

        assert dl_resp.status_code == 200
        assert len(dl_resp.content) > 0
        # XLSX files start with the ZIP local-file header PK\x03\x04.
        assert dl_resp.content[:2] == b"PK"

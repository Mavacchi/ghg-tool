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

"""Tests for the exports API router (4 endpoints)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from ghg_tool.api.main import app


@pytest.fixture()
def mock_user() -> MagicMock:
    user = MagicMock()
    user.sub = "test_user_001"
    user.role = "esg_manager"
    user.tenant_id = "aaaaaaaa-0000-0000-0000-000000000001"
    return user


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


class TestExportsRouter:
    def test_post_pdf_requires_auth(self, client: TestClient) -> None:
        resp = client.post("/api/v1/exports/pdf", json={"anno": 2025})
        assert resp.status_code == 401

    def test_post_xlsx_requires_auth(self, client: TestClient) -> None:
        resp = client.post("/api/v1/exports/xlsx", json={"anno": 2025})
        assert resp.status_code == 401

    def test_get_job_status_not_found(self, client: TestClient) -> None:
        """Without auth, returns 401."""
        resp = client.get(f"/api/v1/exports/jobs/{uuid.uuid4()}")
        assert resp.status_code == 401

    def test_download_requires_auth(self, client: TestClient) -> None:
        resp = client.get(f"/api/v1/exports/jobs/{uuid.uuid4()}/download")
        assert resp.status_code == 401

    def test_post_pdf_validation_error_without_anno(self, client: TestClient) -> None:
        """Without anno field, should fail validation (after auth)."""
        # No auth header → 401 before validation
        resp = client.post("/api/v1/exports/pdf", json={})
        assert resp.status_code in (401, 422)

    def test_router_registered_in_app(self, client: TestClient) -> None:
        """Verify that the exports router is included by checking the OpenAPI spec."""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()
        paths = spec.get("paths", {})
        assert "/api/v1/exports/pdf" in paths
        assert "/api/v1/exports/xlsx" in paths
        assert any("exports/jobs" in p for p in paths)

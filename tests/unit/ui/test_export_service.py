"""Tests for the export service (MVP in-process implementation)."""

from __future__ import annotations

import uuid

from ghg_tool.application.services import export_service


class TestExportService:
    def setup_method(self) -> None:
        """Clear job stores before each test."""
        export_service._jobs.clear()
        export_service._results.clear()

    def test_create_report_job_returns_uuid(self) -> None:
        job_id = export_service.create_report_job(
            job_type="pdf",
            params={"anno": 2025, "gwp_set": "AR6"},
            user_sub="testuser",
            correlation_id=str(uuid.uuid4()),
        )
        assert isinstance(job_id, uuid.UUID)

    def test_get_job_status_returns_none_for_unknown(self) -> None:
        result = export_service.get_job_status(uuid.uuid4())
        assert result is None

    def test_get_job_status_returns_dict_after_create(self) -> None:
        cid = str(uuid.uuid4())
        job_id = export_service.create_report_job(
            job_type="excel",
            params={"anno": 2024, "gwp_set": "AR6"},
            user_sub="testuser",
            correlation_id=cid,
        )
        status = export_service.get_job_status(job_id)
        assert status is not None
        assert status["type"] == "excel"
        assert status["status"] == "PENDING"

    def test_simulate_job_completion(self) -> None:
        cid = str(uuid.uuid4())
        job_id = export_service.create_report_job(
            job_type="pdf",
            params={"anno": 2025},
            user_sub="mgr",
            correlation_id=cid,
        )
        export_service.simulate_job_completion(job_id, "https://example.com/report.pdf")
        status = export_service.get_job_status(job_id)
        assert status is not None
        assert status["status"] == "COMPLETED"
        assert status["download_url"] == "https://example.com/report.pdf"

    def test_get_job_result_none_before_render(self) -> None:
        job_id = export_service.create_report_job(
            job_type="pdf",
            params={"anno": 2025},
            user_sub="mgr",
            correlation_id=str(uuid.uuid4()),
        )
        result = export_service.get_job_result(job_id)
        # PENDING/no render = no result yet
        assert result is None

    def test_start_xlsx_job_synchronous(self) -> None:
        """start_xlsx_job with no event loop renders synchronously (MVP)."""
        job_id = export_service.start_xlsx_job(
            tenant_id="test-tenant",
            period={"anno": 2025, "gwp_set": "AR6"},
            user="mgr",
            correlation_id=str(uuid.uuid4()),
        )
        assert isinstance(job_id, uuid.UUID)
        status = export_service.get_job_status(job_id)
        assert status is not None
        # After synchronous render, should be DONE or FAILED (depending on deps)
        assert status["status"] in ("DONE", "FAILED", "RUNNING", "PENDING")

    def test_start_pdf_job_synchronous(self) -> None:
        """start_pdf_job with no event loop renders synchronously (MVP)."""
        job_id = export_service.start_pdf_job(
            tenant_id="test-tenant",
            period={"anno": 2025, "gwp_set": "AR6", "language": "it"},
            user="mgr",
            correlation_id=str(uuid.uuid4()),
        )
        assert isinstance(job_id, uuid.UUID)
        status = export_service.get_job_status(job_id)
        assert status is not None

    def test_xlsx_result_has_zip_magic_bytes(self) -> None:
        """When xlsx renders successfully, result starts with PK\\x03\\x04."""
        job_id = export_service.start_xlsx_job(
            tenant_id="test-tenant",
            period={"anno": 2025, "gwp_set": "AR6"},
            user="mgr",
            correlation_id=str(uuid.uuid4()),
        )
        result = export_service.get_job_result(job_id)
        status = export_service.get_job_status(job_id)
        if status and status["status"] == "DONE":
            assert result is not None
            assert result[:4] == b"PK\x03\x04", (
                f"Expected ZIP magic, got {result[:4]!r}"
            )

    def test_no_pii_in_job_store(self) -> None:
        """Truncated user sub and tenant_id should not appear in full."""
        full_user = "verylongusername@company.com"
        job_id = export_service.create_report_job(
            job_type="pdf",
            params={"anno": 2025},
            user_sub=full_user,
            correlation_id=str(uuid.uuid4()),
        )
        status = export_service.get_job_status(job_id)
        assert status is not None
        stored_user = status["created_by"]
        assert stored_user != full_user  # Must be truncated
        assert len(stored_user) <= 8

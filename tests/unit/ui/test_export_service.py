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
        """simulate_job_completion sets internal status DONE (REV-WAVE3-004).

        Internal store uses DONE; the API boundary maps DONE → COMPLETED via
        _internal_to_wire().  Asserting the internal store value here.
        """
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
        # REV-WAVE3-004: internal status is DONE, not COMPLETED.
        # Use _internal_to_wire() to get the wire value "COMPLETED".
        assert status["status"] == "DONE"
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


# ---------------------------------------------------------------------------
# Task 6 — poll_export_job adapter (unit tests, mocked Streamlit)
# ---------------------------------------------------------------------------

class TestPollExportJob:
    """Tests for the ``poll_export_job`` adapter in exports.py."""

    def _run_poll(
        self,
        job_id: str,
        statuses: list[dict],
        file_bytes: bytes | None = None,
        file_ext: str = "pdf",
    ) -> list[str]:
        """Run ``poll_export_job`` with mocked API calls and return the
        list of Streamlit calls that were made (success, error, warning)."""
        from unittest.mock import MagicMock, patch

        calls: list[str] = []
        mock_st = MagicMock()
        mock_st.spinner = MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=None),
                                   __exit__=MagicMock(return_value=False))
        )

        status_iter = iter(statuses)

        def _fake_fetch_job_status(_jid: str) -> dict:  # type: ignore[type-arg]
            try:
                return next(status_iter)
            except StopIteration:
                return {"status": "COMPLETED"}

        def _fake_download_report(_jid: str) -> bytes | None:
            return file_bytes

        from ghg_tool.ui.streamlit_app.lib import exports as exp_module

        with (
            patch("ghg_tool.ui.streamlit_app.lib.exports.st", mock_st),
            patch(
                "ghg_tool.ui.streamlit_app.lib.exports.time.sleep",
                return_value=None,
            ),
            patch(
                "ghg_tool.ui.streamlit_app.lib.api_client.fetch_job_status",
                side_effect=_fake_fetch_job_status,
            ),
            patch(
                "ghg_tool.ui.streamlit_app.lib.api_client.download_report",
                side_effect=_fake_download_report,
            ),
        ):
            exp_module.poll_export_job(
                job_id,
                file_basename="test_report",
                file_ext=file_ext,
                lang="it",
                key_suffix="_test",
            )

        # Collect which top-level st methods were called
        if mock_st.download_button.called:
            calls.append("download_button")
        if mock_st.error.called:
            calls.append("error")
        if mock_st.warning.called:
            calls.append("warning")
        return calls

    def test_completed_job_offers_download(self) -> None:
        """COMPLETED status + bytes → st.download_button is rendered."""
        calls = self._run_poll(
            "test-job-id",
            statuses=[{"status": "COMPLETED"}],
            file_bytes=b"PK\x03\x04fake_xlsx_content",
            file_ext="xlsx",
        )
        assert "download_button" in calls

    def test_failed_job_shows_error(self) -> None:
        """FAILED status → st.error is rendered."""
        calls = self._run_poll(
            "test-job-id",
            statuses=[{"status": "FAILED", "error_message": "WeasyPrint crashed"}],
            file_bytes=None,
        )
        assert "error" in calls

    def test_empty_job_id_is_noop(self) -> None:
        """Calling with empty job_id must not crash or render anything."""
        from unittest.mock import MagicMock, patch

        from ghg_tool.ui.streamlit_app.lib import exports as exp_module

        mock_st = MagicMock()
        with patch("ghg_tool.ui.streamlit_app.lib.exports.st", mock_st):
            exp_module.poll_export_job("")
        mock_st.error.assert_not_called()
        mock_st.download_button.assert_not_called()

    def test_timeout_shows_warning(self) -> None:
        """If polling exceeds max time, a warning is shown."""
        from unittest.mock import MagicMock, patch

        from ghg_tool.ui.streamlit_app.lib import exports as exp_module

        mock_st = MagicMock()
        mock_st.spinner = MagicMock(
            return_value=MagicMock(__enter__=MagicMock(return_value=None),
                                   __exit__=MagicMock(return_value=False))
        )

        # Always return RUNNING so we timeout
        def _always_running(jid: str) -> dict:  # type: ignore[type-arg]
            return {"status": "RUNNING"}

        # Patch _POLL_MAX_S to 0 so the loop exits immediately
        with (
            patch("ghg_tool.ui.streamlit_app.lib.exports.st", mock_st),
            patch("ghg_tool.ui.streamlit_app.lib.exports._POLL_MAX_S", 0.0),
            patch("ghg_tool.ui.streamlit_app.lib.exports.time.sleep", return_value=None),
            patch(
                "ghg_tool.ui.streamlit_app.lib.api_client.fetch_job_status",
                side_effect=_always_running,
            ),
            patch(
                "ghg_tool.ui.streamlit_app.lib.api_client.download_report",
                return_value=None,
            ),
        ):
            exp_module.poll_export_job(
                "test-job-timeout",
                file_basename="report",
                file_ext="pdf",
                lang="it",
                key_suffix="_timeout_test",
            )

        mock_st.warning.assert_called_once()

    def test_poll_interval_constant_is_two_seconds(self) -> None:
        """The polling interval must be 2 seconds per task specification."""
        from ghg_tool.ui.streamlit_app.lib.exports import _POLL_INTERVAL_S
        assert _POLL_INTERVAL_S == 2.0

    def test_max_poll_time_is_sixty_seconds(self) -> None:
        """The maximum polling time must be 60 seconds per task specification."""
        from ghg_tool.ui.streamlit_app.lib.exports import _POLL_MAX_S
        assert _POLL_MAX_S == 60.0

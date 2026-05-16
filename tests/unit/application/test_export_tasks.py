"""Unit tests for export_tasks.py — target 90%+ coverage.

Tests cover:
  - _build_report_data: default field extraction, custom anno/gwp_set
  - export_pdf_task: happy path, builder exception propagates
  - export_excel_task: happy path, builder exception propagates

Celery tasks are invoked with ``task.apply(kwargs=...)`` which runs the task
synchronously in the same process without requiring a broker.  This is the
canonical Celery unit-test pattern for bound tasks.
"""

from __future__ import annotations

import base64
import uuid
from unittest.mock import MagicMock, patch

from ghg_tool.application.tasks.export_tasks import (
    _build_report_data,
    export_excel_task,
    export_pdf_task,
)
from ghg_tool.domain.exceptions.export_errors import (
    PDFBuildError,
    XlsxBuildError,
)

# ---------------------------------------------------------------------------
# _build_report_data
# ---------------------------------------------------------------------------

class TestBuildReportData:
    def test_default_anno_is_2025(self) -> None:
        result = _build_report_data({})
        assert result["anno"] == 2025

    def test_custom_anno_overrides_default(self) -> None:
        result = _build_report_data({"anno": 2024})
        assert result["anno"] == 2024

    def test_default_gwp_set_is_ar6(self) -> None:
        result = _build_report_data({})
        assert result["gwp_set"] == "AR6"

    def test_custom_gwp_set_overrides_default(self) -> None:
        result = _build_report_data({"gwp_set": "AR5"})
        assert result["gwp_set"] == "AR5"

    def test_default_language_is_it(self) -> None:
        result = _build_report_data({})
        assert result["language"] == "it"

    def test_custom_language_overrides_default(self) -> None:
        result = _build_report_data({"language": "en"})
        assert result["language"] == "en"

    def test_emissions_list_is_empty_by_default(self) -> None:
        result = _build_report_data({})
        assert result["emissions"] == []

    def test_all_required_keys_present(self) -> None:
        result = _build_report_data({})
        required = {"anno", "gwp_set", "language", "emissions", "biogenic", "factors",
                    "dq_findings", "audit_trail"}
        assert required.issubset(result.keys())


# ---------------------------------------------------------------------------
# export_pdf_task
# ---------------------------------------------------------------------------

class TestExportPdfTask:
    """Tests using task.apply() for synchronous in-process Celery execution."""

    def test_happy_path_returns_correct_schema(self) -> None:
        """export_pdf_task returns the expected result dict on success."""
        tenant_id = str(uuid.uuid4())
        fake_bytes = b"%PDF-1.4 fake pdf content"

        mock_builder_instance = MagicMock()
        mock_builder_instance.build = MagicMock(return_value=fake_bytes)
        mock_builder_cls = MagicMock(return_value=mock_builder_instance)

        with patch("ghg_tool.ui.pdf.builder.PDFBuilder", mock_builder_cls):
            ar = export_pdf_task.apply(
                kwargs={"tenant_id": tenant_id, "params": {"anno": 2025, "gwp_set": "AR6"}},
            )

        result = ar.result
        assert result["job_type"] == "pdf"
        assert result["tenant_id"] == tenant_id
        assert result["size_bytes"] == len(fake_bytes)
        decoded = base64.b64decode(result["result_b64"])
        assert decoded == fake_bytes

    def test_builder_called_with_report_data(self) -> None:
        """PDFBuilder.build is called with the assembled report_data dict."""
        fake_bytes = b"%PDF-fake"
        mock_builder_instance = MagicMock()
        mock_builder_instance.build = MagicMock(return_value=fake_bytes)
        mock_builder_cls = MagicMock(return_value=mock_builder_instance)

        with patch("ghg_tool.ui.pdf.builder.PDFBuilder", mock_builder_cls):
            export_pdf_task.apply(
                kwargs={
                    "tenant_id": str(uuid.uuid4()),
                    "params": {"anno": 2024, "language": "en"},
                },
            )

        mock_builder_cls.assert_called_once()
        mock_builder_instance.build.assert_called_once()
        call_arg = mock_builder_instance.build.call_args[0][0]
        assert call_arg["anno"] == 2024
        assert call_arg["language"] == "en"

    def test_builder_exception_is_stored_as_failure(self) -> None:
        """Exceptions from PDFBuilder are captured as FAILURE state."""
        mock_builder_instance = MagicMock()
        mock_builder_instance.build = MagicMock(side_effect=RuntimeError("render exploded"))
        mock_builder_cls = MagicMock(return_value=mock_builder_instance)

        with patch("ghg_tool.ui.pdf.builder.PDFBuilder", mock_builder_cls):
            ar = export_pdf_task.apply(
                kwargs={"tenant_id": str(uuid.uuid4()), "params": {}},
                throw=False,
            )

        assert ar.failed()
        # Task wraps the underlying RuntimeError in PDFBuildError (chained
        # via `raise ... from exc`), so the stored Celery result is the
        # wrapper; the original RuntimeError is the __cause__.
        assert isinstance(ar.result, PDFBuildError)
        assert isinstance(ar.result.__cause__, RuntimeError)

    def test_result_b64_is_valid_base64(self) -> None:
        fake_bytes = b"PDF content bytes"
        mock_builder_instance = MagicMock()
        mock_builder_instance.build = MagicMock(return_value=fake_bytes)
        mock_builder_cls = MagicMock(return_value=mock_builder_instance)

        with patch("ghg_tool.ui.pdf.builder.PDFBuilder", mock_builder_cls):
            ar = export_pdf_task.apply(
                kwargs={"tenant_id": str(uuid.uuid4()), "params": {}},
            )

        base64.b64decode(ar.result["result_b64"])  # must not raise

    def test_size_bytes_matches_actual_byte_length(self) -> None:
        fake_bytes = b"x" * 1000
        mock_builder_instance = MagicMock()
        mock_builder_instance.build = MagicMock(return_value=fake_bytes)
        mock_builder_cls = MagicMock(return_value=mock_builder_instance)

        with patch("ghg_tool.ui.pdf.builder.PDFBuilder", mock_builder_cls):
            ar = export_pdf_task.apply(
                kwargs={"tenant_id": str(uuid.uuid4()), "params": {}},
            )

        assert ar.result["size_bytes"] == 1000


# ---------------------------------------------------------------------------
# export_excel_task
# ---------------------------------------------------------------------------

class TestExportExcelTask:
    def test_happy_path_returns_correct_schema(self) -> None:
        tenant_id = str(uuid.uuid4())
        fake_bytes = b"PK excel-content"

        mock_builder_instance = MagicMock()
        mock_builder_instance.build = MagicMock(return_value=fake_bytes)
        mock_builder_cls = MagicMock(return_value=mock_builder_instance)

        with patch("ghg_tool.ui.excel.builder.XlsxBuilder", mock_builder_cls):
            ar = export_excel_task.apply(
                kwargs={"tenant_id": tenant_id, "params": {"anno": 2025, "gwp_set": "AR5"}},
            )

        result = ar.result
        assert result["job_type"] == "excel"
        assert result["tenant_id"] == tenant_id
        assert result["size_bytes"] == len(fake_bytes)
        decoded = base64.b64decode(result["result_b64"])
        assert decoded == fake_bytes

    def test_builder_called_with_assembled_data(self) -> None:
        fake_bytes = b"xlsx-bytes"
        mock_builder_instance = MagicMock()
        mock_builder_instance.build = MagicMock(return_value=fake_bytes)
        mock_builder_cls = MagicMock(return_value=mock_builder_instance)

        with patch("ghg_tool.ui.excel.builder.XlsxBuilder", mock_builder_cls):
            export_excel_task.apply(
                kwargs={
                    "tenant_id": str(uuid.uuid4()),
                    "params": {"gwp_set": "AR6"},
                },
            )

        mock_builder_cls.assert_called_once()
        mock_builder_instance.build.assert_called_once()
        call_arg = mock_builder_instance.build.call_args[0][0]
        assert call_arg["gwp_set"] == "AR6"

    def test_builder_exception_is_stored_as_failure(self) -> None:
        mock_builder_instance = MagicMock()
        mock_builder_instance.build = MagicMock(side_effect=ValueError("bad data"))
        mock_builder_cls = MagicMock(return_value=mock_builder_instance)

        with patch("ghg_tool.ui.excel.builder.XlsxBuilder", mock_builder_cls):
            ar = export_excel_task.apply(
                kwargs={"tenant_id": str(uuid.uuid4()), "params": {}},
                throw=False,
            )

        assert ar.failed()
        # Same wrapping contract as the PDF task: the underlying ValueError
        # is wrapped in XlsxBuildError and chained as __cause__.
        assert isinstance(ar.result, XlsxBuildError)
        assert isinstance(ar.result.__cause__, ValueError)

    def test_size_bytes_matches_actual_byte_length(self) -> None:
        fake_bytes = b"y" * 2048
        mock_builder_instance = MagicMock()
        mock_builder_instance.build = MagicMock(return_value=fake_bytes)
        mock_builder_cls = MagicMock(return_value=mock_builder_instance)

        with patch("ghg_tool.ui.excel.builder.XlsxBuilder", mock_builder_cls):
            ar = export_excel_task.apply(
                kwargs={"tenant_id": str(uuid.uuid4()), "params": {}},
            )

        assert ar.result["size_bytes"] == 2048

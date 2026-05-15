"""Tests for the PDF builder — verifies PDF magic bytes and structure (FR-28).

WeasyPrint requires system fonts and may not be available in all CI
environments.  The test is marked with a skip guard and a clear error
message when WeasyPrint cannot render.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def sample_report_data() -> dict:  # type: ignore[type-arg]
    """Minimal report_data for PDF generation tests."""
    return {
        "anno": 2025,
        "gwp_set": "AR6",
        "language": "it",
        "emissions": [
            {
                "scope": 1, "sub_scope": "combustion", "codice_sito": "IANO",
                "anno": 2025, "tco2e": 1234.5,
                "factor_source": "DEFRA", "factor_version": "2024",
                "gwp_set": "AR6", "methodology": "activity-based",
                "co2_tonne": 1200.0, "ch4_tco2e": 20.0, "n2o_tco2e": 14.5,
                "disclosure_notes": None,
            },
            {
                "scope": 2, "sub_scope": "LB", "codice_sito": "IANO",
                "anno": 2025, "tco2e": 500.0,
                "factor_source": "ISPRA", "factor_version": "2024",
                "gwp_set": "AR6", "methodology": "location-based",
                "co2_tonne": 500.0, "co2_biogenic_tonne": None,
                "co2_fossil_tonne": None, "disclosure_notes": None,
            },
            {
                "scope": 3, "sub_scope": "Cat1", "codice_sito": None,
                "anno": 2025, "tco2e": 3200.0,
                "factor_source": "ecoinvent", "factor_version": "v3.10",
                "gwp_set": "AR6", "methodology": "mass-based",
                "co2_tonne": None, "ch4_tco2e": None, "n2o_tco2e": None,
                "disclosure_notes": None,
            },
        ],
        "biogenic": [
            {
                "codice_sito": "IANO", "anno": 2025, "sub_scope": "biogenic",
                "co2_biogenic_tonne": 150.0, "co2_fossil_tonne": 1000.0,
                "factor_source": "DEFRA", "factor_version": "2024",
                "gwp_set": "AR6", "tco2e": 0.0,
            }
        ],
        "factors": [],
        "dq_findings": [],
        "audit_trail": [],
        "intensity_rows": [],
    }


def _weasyprint_works() -> bool:
    """Probe whether the installed WeasyPrint can actually render.

    WeasyPrint 62.3 with pydyf 0.12.1 has a known version mismatch that
    causes ``AttributeError: 'super' object has no attribute 'transform'``
    on every render call.  We detect this at import time so that the PDF
    magic-bytes tests can be skipped gracefully in affected environments.

    Returns:
        True when WeasyPrint renders a trivial document without error.
    """
    try:
        import weasyprint  # type: ignore[import-untyped]
        html = weasyprint.HTML(string="<html><body><p>probe</p></body></html>")
        pdf = html.write_pdf()
        return isinstance(pdf, bytes) and pdf[:4] == b"%PDF"
    except Exception:  # noqa: BLE001
        return False


_WEASYPRINT_FUNCTIONAL = _weasyprint_works()


class TestPDFBuilderFallback:
    """Tests that use the WeasyPrint render path."""

    @pytest.mark.skipif(
        not _WEASYPRINT_FUNCTIONAL,
        reason="WeasyPrint is not functional in this environment "
               "(version mismatch with pydyf — known WeasyPrint 62.3/pydyf 0.12.1 issue)",
    )
    def test_build_returns_bytes(self, sample_report_data: dict) -> None:  # type: ignore[type-arg]
        """PDF build must return bytes (uses WeasyPrint with fallback HTML)."""
        from ghg_tool.ui.pdf.builder import PDFBuilder

        builder = PDFBuilder()
        result = builder.build(sample_report_data)
        assert isinstance(result, bytes)
        assert len(result) > 0

    @pytest.mark.skipif(
        not _WEASYPRINT_FUNCTIONAL,
        reason="WeasyPrint is not functional in this environment "
               "(version mismatch with pydyf — known WeasyPrint 62.3/pydyf 0.12.1 issue)",
    )
    def test_pdf_magic_bytes(self, sample_report_data: dict) -> None:  # type: ignore[type-arg]
        """PDF must start with '%PDF-' magic bytes."""
        from ghg_tool.ui.pdf.builder import PDFBuilder

        builder = PDFBuilder()
        result = builder.build(sample_report_data)
        assert result[:4] == b"%PDF", (
            f"Expected '%PDF' magic bytes, got {result[:4]!r}"
        )

    def test_template_declares_company_name(self) -> None:
        """ESRS E1 main template must declare a reporting-entity placeholder.

        Bytes-level search on the PDF output is unreliable because
        WeasyPrint/pydyf compress text streams (FlateDecode). We verify
        the template source itself instead.

        The brand was previously hardcoded ('Saturnia'); the rebrand wave
        replaced the literal with a Jinja ``{{ company_name }}`` placeholder
        injected at render time from ``GHG_COMPANY_NAME``. The invariant
        we now enforce is that the placeholder exists.
        """
        from pathlib import Path

        template = Path(
            "src/ghg_tool/ui/pdf/templates/esrs_e1.html"
        ).read_text(encoding="utf-8")
        assert "{{ company_name }}" in template, (
            "Reporting entity placeholder '{{ company_name }}' must appear "
            "in esrs_e1.html (rebrand: hardcoded names removed in favour "
            "of GHG_COMPANY_NAME-injected placeholder)."
        )


class TestPDFBuilderHTMLRendering:
    """Tests for HTML rendering without WeasyPrint (unit tests for logic)."""

    def test_fallback_html_contains_adr007_disclaimer(
        self, sample_report_data: dict  # type: ignore[type-arg]
    ) -> None:
        """Fallback HTML must contain the mandatory ADR-007 biogenic disclaimer."""
        from ghg_tool.ui.pdf.builder import _fallback_html

        html = _fallback_html({
            "anno": 2025,
            "gwp_set": "AR6",
            "generated_at": "2026-05-13T00:00:00Z",
            "dashboard_id": "esg-main-2026",
            "dashboard_version": "1.0.0",
        })
        assert "ADR-007" in html
        assert "biogenich" in html.lower() or "biogenic" in html.lower()
        assert "E1-7" in html

    def test_fallback_html_contains_gwp_set(
        self, sample_report_data: dict  # type: ignore[type-arg]
    ) -> None:
        from ghg_tool.ui.pdf.builder import _fallback_html

        html = _fallback_html({
            "anno": 2025,
            "gwp_set": "AR6",
            "generated_at": "2026-05-13T00:00:00Z",
            "dashboard_id": "esg-main-2026",
            "dashboard_version": "1.0.0",
        })
        assert "AR6" in html

    def test_fallback_html_contains_methodology(self) -> None:
        from ghg_tool.ui.pdf.builder import _fallback_html

        html = _fallback_html({
            "anno": 2025,
            "gwp_set": "AR6",
            "generated_at": "2026-05-13T00:00:00Z",
            "dashboard_id": "esg-main-2026",
            "dashboard_version": "1.0.0",
        })
        assert "GHG Protocol" in html

    def test_fallback_html_contains_factor_source(self) -> None:
        from ghg_tool.ui.pdf.builder import _fallback_html

        html = _fallback_html({
            "anno": 2025,
            "gwp_set": "AR6",
            "generated_at": "2026-05-13T00:00:00Z",
            "dashboard_id": "esg-main-2026",
            "dashboard_version": "1.0.0",
        })
        assert "ISPRA" in html

    def test_scope2_pairs_lb_mb_separated(self) -> None:
        from ghg_tool.ui.pdf.builder import _build_scope2_pairs

        rows = [
            {"codice_sito": "IANO", "anno": 2025, "sub_scope": "LB", "tco2e": 500.0,
             "factor_source": "ISPRA", "factor_version": "2024", "gwp_set": "AR6"},
            {"codice_sito": "IANO", "anno": 2025, "sub_scope": "MB", "tco2e": 0.0,
             "factor_source": "ISPRA", "factor_version": "2024", "gwp_set": "AR6"},
        ]
        result = _build_scope2_pairs(rows)
        assert len(result) == 1
        assert result[0]["tco2e_lb"] == 500.0
        assert result[0]["tco2e_mb"] == 0.0

    def test_enrich_scope3_adds_category_num(self) -> None:
        from ghg_tool.ui.pdf.builder import _enrich_scope3

        row = {"sub_scope": "Cat1", "tco2e": 100.0}
        enriched = _enrich_scope3(row)
        assert enriched["category_num"] == "1"
        assert "Beni" in enriched["category_name"]

    def test_disclaimer_contains_isae_3000(self) -> None:
        from ghg_tool.ui.pdf.builder import _get_disclaimer

        for lang in ("it", "en"):
            disc = _get_disclaimer(lang)
            assert "ISAE 3000" in disc

    def test_disclaimer_it(self) -> None:
        from ghg_tool.ui.pdf.builder import _get_disclaimer

        disc = _get_disclaimer("it")
        assert "GHG Accounting Tool" in disc
        assert "ESRS E1" in disc

    def test_disclaimer_en(self) -> None:
        from ghg_tool.ui.pdf.builder import _get_disclaimer

        disc = _get_disclaimer("en")
        assert "GHG Accounting Tool" in disc
        assert "ESRS E1" in disc

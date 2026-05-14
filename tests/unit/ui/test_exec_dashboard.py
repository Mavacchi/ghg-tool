"""Tests for ExecDashboardBuilder (FR-28 executive one-pager).

All tests that require WeasyPrint are guarded by the same functional probe
used in test_pdf_builder.py. HTML-rendering tests run without WeasyPrint.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def minimal_data() -> dict:
    """Minimal valid data dict for ExecDashboardBuilder.build()."""
    return {
        "anno": 2025,
        "prior_anno": 2024,
        "company_name": "Gresmalt S.p.A.",
        "gwp_set": "AR6",
        "language": "it",
        "generated_at": "2026-05-14T09:00:00+00:00",
        "dashboard_id": "esg-exec-2026",
        "dashboard_version": "1.0.0",
        "totals_current": {
            "scope1": 1200.0,
            "scope2_lb": 500.0,
            "scope2_mb": 300.0,
            "scope3": 8000.0,
            "biogenic_memo": 150.0,
            "total_lb": 9700.0,
        },
        "totals_prior": {
            "scope1": 1400.0,
            "scope2_lb": 600.0,
            "scope2_mb": 350.0,
            "scope3": 9000.0,
            "biogenic_memo": 180.0,
            "total_lb": 11000.0,
        },
        "intensity_revenue": 42.5,
        "intensity_m2": 87.3,
        "intensity_revenue_prior": 45.0,
        "intensity_m2_prior": 92.0,
        "target": {
            "name": "SBTi 1.5C Target",
            "target_year": 2030,
            "target_tco2e": 5000.0,
            "on_track_status": "ON_TRACK",
            "trajectory_note": "Trajectory 2025 = 9700 tCO2e; actual = 9700 tCO2e",
        },
        "top_scope3_categories": [
            {"sub_scope": "Cat1", "category_label": "Cat. 1 Purchased goods", "tco2e": 4000.0, "pct": 50.0},
            {"sub_scope": "Cat4", "category_label": "Cat. 4 Upstream transport", "tco2e": 2000.0, "pct": 25.0},
            {"sub_scope": "Cat11", "category_label": "Cat. 11 Use of sold products", "tco2e": 1000.0, "pct": 12.5},
        ],
        "dq_summary": {"crit_open": 2, "warn_open": 5, "total_findings": 10},
        "assurance_status": "limited",
        "signed_by_esg_manager": "Mario Rossi",
    }


@pytest.fixture()
def no_target_data(minimal_data: dict) -> dict:
    """Data dict with target explicitly absent."""
    d = dict(minimal_data)
    d["target"] = None
    return d


@pytest.fixture()
def zero_emissions_data(minimal_data: dict) -> dict:
    """Data dict where all emission values are zero."""
    d = dict(minimal_data)
    d["totals_current"] = {
        "scope1": 0.0, "scope2_lb": 0.0, "scope2_mb": 0.0,
        "scope3": 0.0, "biogenic_memo": 0.0, "total_lb": 0.0,
    }
    d["totals_prior"] = {
        "scope1": 0.0, "scope2_lb": 0.0, "scope2_mb": 0.0,
        "scope3": 0.0, "biogenic_memo": 0.0, "total_lb": 0.0,
    }
    d["intensity_revenue"] = 0.0
    d["intensity_m2"] = 0.0
    d["top_scope3_categories"] = []
    return d


# ---------------------------------------------------------------------------
# WeasyPrint probe (same pattern as test_pdf_builder.py)
# ---------------------------------------------------------------------------

def _weasyprint_works() -> bool:
    """Return True when WeasyPrint can render without errors."""
    try:
        import weasyprint  # type: ignore[import-untyped]
        html = weasyprint.HTML(string="<html><body><p>probe</p></body></html>")
        pdf = html.write_pdf()
        return isinstance(pdf, bytes) and pdf[:4] == b"%PDF"
    except Exception:  # noqa: BLE001
        return False


_WEASYPRINT_FUNCTIONAL = _weasyprint_works()

_skip_if_no_weasyprint = pytest.mark.skipif(
    not _WEASYPRINT_FUNCTIONAL,
    reason=(
        "WeasyPrint is not functional in this environment "
        "(version mismatch with pydyf -- known WeasyPrint 62.3/pydyf 0.12.1 issue)"
    ),
)


# ---------------------------------------------------------------------------
# PDF bytes tests (require WeasyPrint)
# ---------------------------------------------------------------------------

class TestExecDashboardPDFBytes:

    @_skip_if_no_weasyprint
    def test_build_returns_pdf_bytes_starting_with_pct_pdf(
        self, minimal_data: dict
    ) -> None:
        """build() must return bytes beginning with the %PDF magic sequence."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        result = ExecDashboardBuilder().build(minimal_data)
        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF", f"Expected %PDF magic bytes, got {result[:4]!r}"

    @_skip_if_no_weasyprint
    def test_build_handles_missing_target_gracefully(
        self, no_target_data: dict
    ) -> None:
        """build() must succeed and return PDF bytes when target is None."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        result = ExecDashboardBuilder().build(no_target_data)
        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF"

    @_skip_if_no_weasyprint
    def test_build_handles_zero_emissions_year(
        self, zero_emissions_data: dict
    ) -> None:
        """build() must succeed when all scope totals are zero (no division errors)."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        result = ExecDashboardBuilder().build(zero_emissions_data)
        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# HTML rendering tests (no WeasyPrint required)
# ---------------------------------------------------------------------------

class TestExecDashboardHTMLRendering:

    def test_build_includes_company_name_in_html_render(
        self, minimal_data: dict
    ) -> None:
        """Rendered HTML must contain the company name from the data dict."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        html = ExecDashboardBuilder().render_html_only(minimal_data)
        assert "Gresmalt S.p.A." in html

    def test_build_renders_all_five_kpi_cards(
        self, minimal_data: dict
    ) -> None:
        """Rendered HTML must contain all five KPI card labels."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        html = ExecDashboardBuilder().render_html_only(minimal_data)
        # Check that all five scope labels appear (class kpi-label content)
        assert "Scope 1" in html
        assert "Scope 2 LB" in html
        assert "Scope 2 MB" in html
        assert "Scope 3" in html
        # Total card
        assert "kpi-card total" in html

    def test_build_handles_missing_target_gracefully_html(
        self, no_target_data: dict
    ) -> None:
        """Rendered HTML must not crash and must show no-target label when target is None."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        html = ExecDashboardBuilder().render_html_only(no_target_data)
        # Should show the no-target placeholder text (IT label)
        assert "Nessun target SBTi attivo" in html

    def test_build_handles_zero_emissions_html(
        self, zero_emissions_data: dict
    ) -> None:
        """Rendered HTML must not crash with all-zero totals."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        html = ExecDashboardBuilder().render_html_only(zero_emissions_data)
        assert "exec-header" in html

    def test_html_contains_adr007_disclaimer(self, minimal_data: dict) -> None:
        """Rendered HTML must include the mandatory ADR-007 biogenic disclaimer."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        html = ExecDashboardBuilder().render_html_only(minimal_data)
        assert "ADR-007" in html
        assert "biogen" in html.lower()

    def test_html_contains_gwp_set(self, minimal_data: dict) -> None:
        """Rendered HTML must show the GWP set in the footer."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        html = ExecDashboardBuilder().render_html_only(minimal_data)
        assert "AR6" in html

    def test_html_contains_dashboard_id(self, minimal_data: dict) -> None:
        """Rendered HTML must contain the dashboard_id for audit traceability."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        html = ExecDashboardBuilder().render_html_only(minimal_data)
        assert "esg-exec-2026" in html

    def test_html_on_track_status_renders(self, minimal_data: dict) -> None:
        """Rendered HTML must show the traffic-light status for ON_TRACK."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        html = ExecDashboardBuilder().render_html_only(minimal_data)
        assert "on-track" in html

    def test_html_off_track_status_renders(self, minimal_data: dict) -> None:
        """Rendered HTML must use the off-track class for OFF_TRACK status."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        data = dict(minimal_data)
        data["target"] = dict(minimal_data["target"])  # type: ignore[arg-type]
        data["target"]["on_track_status"] = "OFF_TRACK"  # type: ignore[index]

        html = ExecDashboardBuilder().render_html_only(data)
        assert "off-track" in html

    def test_english_labels_used_when_language_en(self, minimal_data: dict) -> None:
        """Rendered HTML must use English labels when language='en'."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        data = dict(minimal_data)
        data["language"] = "en"
        html = ExecDashboardBuilder().render_html_only(data)
        assert "Reporting year" in html

    def test_italian_labels_used_when_language_it(self, minimal_data: dict) -> None:
        """Rendered HTML must use Italian labels when language='it'."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        html = ExecDashboardBuilder().render_html_only(minimal_data)
        assert "Anno di rendicontazione" in html

    def test_scope3_hotspots_rendered_in_table(self, minimal_data: dict) -> None:
        """Rendered HTML must contain Scope 3 category labels."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        html = ExecDashboardBuilder().render_html_only(minimal_data)
        assert "Cat. 1 Purchased goods" in html
        assert "Cat. 4 Upstream transport" in html

    def test_dq_summary_rendered(self, minimal_data: dict) -> None:
        """Rendered HTML must contain DQ counts."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        html = ExecDashboardBuilder().render_html_only(minimal_data)
        assert "2 CRIT" in html
        assert "5 WARN" in html

    def test_esg_manager_signature_rendered(self, minimal_data: dict) -> None:
        """Rendered HTML must show the ESG manager name when provided."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        html = ExecDashboardBuilder().render_html_only(minimal_data)
        assert "Mario Rossi" in html

    def test_no_em_dashes_in_output(self, minimal_data: dict) -> None:
        """Project policy: no em-dashes in any rendered output."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        html = ExecDashboardBuilder().render_html_only(minimal_data)
        assert "—" not in html, "Em-dash found in rendered HTML output"


# ---------------------------------------------------------------------------
# Fallback HTML tests (no Jinja2 / no WeasyPrint)
# ---------------------------------------------------------------------------

class TestExecDashboardFallbackHTML:

    def test_fallback_html_contains_company_name(self) -> None:
        """Fallback HTML must include the company name."""
        from ghg_tool.ui.pdf.exec_dashboard import _fallback_html_exec

        html = _fallback_html_exec({
            "anno": 2025,
            "gwp_set": "AR6",
            "generated_at": "2026-05-14T09:00:00Z",
            "dashboard_id": "esg-exec-2026",
            "dashboard_version": "1.0.0",
            "company_name": "Gresmalt Test",
            "totals_current": {"scope1": 0, "scope2_lb": 0, "scope3": 0, "total_lb": 0},
            "dq_summary": {"crit_open": 0, "warn_open": 0, "total_findings": 0},
            "assurance_status": "none",
        })
        assert "Gresmalt Test" in html

    def test_fallback_html_contains_adr007(self) -> None:
        """Fallback HTML must contain the ADR-007 biogenic disclaimer."""
        from ghg_tool.ui.pdf.exec_dashboard import _fallback_html_exec

        html = _fallback_html_exec({
            "anno": 2025,
            "gwp_set": "AR6",
            "generated_at": "2026-05-14T09:00:00Z",
            "dashboard_id": "x",
            "dashboard_version": "0",
            "company_name": "",
            "totals_current": {"scope1": 0, "scope2_lb": 0, "scope3": 0, "total_lb": 0},
            "dq_summary": {"crit_open": 0, "warn_open": 0, "total_findings": 0},
            "assurance_status": "none",
        })
        assert "ADR-007" in html
        assert "biogen" in html.lower()


# ---------------------------------------------------------------------------
# Unit tests for internal helpers
# ---------------------------------------------------------------------------

class TestPctDelta:

    def test_positive_delta(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _pct_delta

        result = _pct_delta(110.0, 100.0)
        assert result is not None
        assert result["css"] == "up"
        assert "10.0" in result["pct"]

    def test_negative_delta(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _pct_delta

        result = _pct_delta(90.0, 100.0)
        assert result is not None
        assert result["css"] == "down"
        assert "-10.0" in result["pct"]

    def test_flat_delta(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _pct_delta

        result = _pct_delta(100.0, 100.0)
        assert result is not None
        assert result["css"] == "flat"

    def test_none_when_prior_zero(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _pct_delta

        assert _pct_delta(100.0, 0.0) is None

    def test_none_when_prior_none(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _pct_delta

        assert _pct_delta(100.0, None) is None

    def test_none_when_current_none(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _pct_delta

        assert _pct_delta(None, 100.0) is None


class TestFmtNum:

    def test_large_number_formatted(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _fmt_num

        assert _fmt_num(1234567.0) == "1,234,567"

    def test_zero(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _fmt_num

        assert _fmt_num(0.0) == "0"

    def test_none_returns_na(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _fmt_num

        assert _fmt_num(None) == "N/A"

    def test_string_number_parsed(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _fmt_num

        assert _fmt_num("9700") == "9,700"

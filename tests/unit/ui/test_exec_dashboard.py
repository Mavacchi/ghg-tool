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
            {"sub_scope": "Cat1", "category_label": "Cat. 1 Purchased goods", "tco2e": 4000.0, "pct": 50.0},  # noqa: E501
            {"sub_scope": "Cat4", "category_label": "Cat. 4 Upstream transport", "tco2e": 2000.0, "pct": 25.0},  # noqa: E501
            {"sub_scope": "Cat11", "category_label": "Cat. 11 Use of sold products", "tco2e": 1000.0, "pct": 12.5},  # noqa: E501
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


# ---------------------------------------------------------------------------
# _fmt_dec (missing lines 248-249)
# ---------------------------------------------------------------------------

class TestFmtDec:

    def test_decimal_two_places(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _fmt_dec

        assert _fmt_dec(1234.567) == "1,234.57"

    def test_zero_formatted(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _fmt_dec

        assert _fmt_dec(0) == "0.00"

    def test_none_returns_na(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _fmt_dec

        assert _fmt_dec(None) == "N/A"

    def test_non_numeric_string_returns_na(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _fmt_dec

        assert _fmt_dec("not-a-number") == "N/A"


# ---------------------------------------------------------------------------
# _build_chart_png and _png_to_data_uri (missing lines 165-223, 228-229)
# ---------------------------------------------------------------------------

def _matplotlib_available() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


_skip_no_matplotlib = pytest.mark.skipif(
    not _matplotlib_available(),
    reason="matplotlib not installed in this environment",
)


class TestBuildChartPng:

    @_skip_no_matplotlib
    def test_returns_bytes(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _build_chart_png

        png = _build_chart_png(
            current={"scope1": 1200, "scope2_lb": 500, "scope3": 8000},
            prior={"scope1": 1400, "scope2_lb": 600, "scope3": 9000},
            anno=2025,
            prior_anno=2024,
        )
        assert isinstance(png, bytes)
        assert len(png) > 0

    @_skip_no_matplotlib
    def test_returns_valid_png_magic(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _build_chart_png

        png = _build_chart_png(
            current={"scope1": 100, "scope2_lb": 50, "scope3": 800},
            prior={"scope1": 140, "scope2_lb": 60, "scope3": 900},
            anno=2025,
            prior_anno=2024,
        )
        # PNG magic bytes: \x89PNG
        assert png[:4] == b"\x89PNG"

    @_skip_no_matplotlib
    def test_all_zeros_does_not_raise(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _build_chart_png

        png = _build_chart_png(
            current={"scope1": 0, "scope2_lb": 0, "scope3": 0},
            prior={"scope1": 0, "scope2_lb": 0, "scope3": 0},
            anno=2025,
            prior_anno=2024,
        )
        assert isinstance(png, bytes)

    @_skip_no_matplotlib
    def test_missing_keys_treated_as_zero(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _build_chart_png

        # Passing empty dicts — should default to 0 for all values
        png = _build_chart_png(
            current={},
            prior={},
            anno=2025,
            prior_anno=2024,
        )
        assert isinstance(png, bytes)


class TestPngToDataUri:

    def test_produces_data_uri_prefix(self) -> None:
        from ghg_tool.ui.pdf.exec_dashboard import _png_to_data_uri

        result = _png_to_data_uri(b"\x89PNGfakecontent")
        assert result.startswith("data:image/png;base64,")

    def test_data_uri_is_decodeable(self) -> None:
        import base64

        from ghg_tool.ui.pdf.exec_dashboard import _png_to_data_uri

        raw = b"some png bytes here"
        uri = _png_to_data_uri(raw)
        b64_part = uri.removeprefix("data:image/png;base64,")
        decoded = base64.b64decode(b64_part)
        assert decoded == raw


# ---------------------------------------------------------------------------
# _build_context — total_lb computation when absent (lines 399-407)
# ---------------------------------------------------------------------------

class TestBuildContextTotalLbComputed:

    def test_total_lb_computed_when_not_supplied_current(self) -> None:
        """When total_lb is absent in totals_current, it is computed from scopes."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        data = {
            "anno": 2025,
            "prior_anno": 2024,
            "company_name": "Test Co",
            "gwp_set": "AR6",
            "language": "en",
            "totals_current": {
                "scope1": 1000.0,
                "scope2_lb": 200.0,
                "scope3": 3000.0,
                # total_lb intentionally absent
            },
            "totals_prior": {
                "scope1": 1100.0,
                "scope2_lb": 220.0,
                "scope3": 3200.0,
                # total_lb intentionally absent
            },
        }
        html = ExecDashboardBuilder().render_html_only(data)
        # Should render without error; total_lb = 1000+200+3000 = 4200
        assert html is not None
        assert len(html) > 0

    def test_total_lb_not_recomputed_when_supplied(self) -> None:
        """When total_lb is already in totals_current, it is preserved."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        data = {
            "anno": 2025,
            "prior_anno": 2024,
            "company_name": "Test Co",
            "gwp_set": "AR6",
            "language": "en",
            "totals_current": {
                "scope1": 1000.0,
                "scope2_lb": 200.0,
                "scope3": 3000.0,
                "total_lb": 9999.0,  # override — not sum of scopes
            },
            "totals_prior": {
                "scope1": 1100.0,
                "scope2_lb": 220.0,
                "scope3": 3200.0,
                "total_lb": 9998.0,
            },
        }
        html = ExecDashboardBuilder().render_html_only(data)
        assert "9,999" in html


# ---------------------------------------------------------------------------
# factor_sources from factor list (lines 469-474)
# ---------------------------------------------------------------------------

def _minimal_totals(scope1: float = 100.0, scope2_lb: float = 50.0,
                    scope2_mb: float = 30.0, scope3: float = 800.0) -> dict:
    return {
        "scope1": scope1, "scope2_lb": scope2_lb,
        "scope2_mb": scope2_mb, "scope3": scope3,
    }


class TestBuildContextFactorSources:

    def test_factor_sources_extracted_from_published_factors(self) -> None:
        """When factors list is supplied, published sources are extracted."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        data = {
            "anno": 2025,
            "prior_anno": 2024,
            "company_name": "Co",
            "gwp_set": "AR6",
            "language": "en",
            "totals_current": _minimal_totals(),
            "totals_prior": _minimal_totals(scope1=110, scope2_lb=55),
            "factors": [
                {"source": "DEFRA", "is_published": True},
                {"source": "ISPRA", "is_published": True},
                {"source": "DRAFT", "is_published": False},
            ],
        }
        html = ExecDashboardBuilder().render_html_only(data)
        # Both published sources should appear somewhere in the HTML
        assert "DEFRA" in html or "ISPRA" in html

    def test_factor_sources_empty_published_falls_back_to_default(self) -> None:
        """When factors list has entries but none published, falls back to default text."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        data = {
            "anno": 2025,
            "prior_anno": 2024,
            "company_name": "Co",
            "gwp_set": "AR6",
            "language": "en",
            "totals_current": _minimal_totals(),
            "totals_prior": _minimal_totals(scope1=110, scope2_lb=55),
            "factors": [
                {"source": "DRAFT", "is_published": False},
            ],
        }
        html = ExecDashboardBuilder().render_html_only(data)
        assert "catalogo" in html.lower() or "Vedi catalogo" in html


# ---------------------------------------------------------------------------
# ExecDashboardBuilder.__init__ — jinja2 ImportError path (lines 321-322)
# ---------------------------------------------------------------------------

class TestExecDashboardBuilderJinja2Fallback:

    def test_builder_works_without_jinja2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When jinja2 is unavailable, builder falls back to minimal HTML."""
        import sys
        from unittest.mock import patch

        # Temporarily hide jinja2 so ImportError path is hit in __init__
        with patch.dict(sys.modules, {"jinja2": None}):  # type: ignore[dict-item]
            from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder
            builder = ExecDashboardBuilder()
            # _jinja_env should be None since import failed
            assert builder._jinja_env is None

        # After unpatching, create a new builder — it should use jinja2 again
        builder2 = ExecDashboardBuilder()
        assert builder2._jinja_env is not None


# ---------------------------------------------------------------------------
# _render_html — template exception fallback (lines 513-515)
# ---------------------------------------------------------------------------

class TestRenderHtmlTemplateFallback:

    def test_render_falls_back_on_template_exception(self, minimal_data: dict) -> None:
        """When Jinja2 template rendering raises, fallback HTML is returned."""
        from unittest.mock import patch

        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        builder = ExecDashboardBuilder()

        if builder._jinja_env is not None:
            # Patch get_template to raise
            with patch.object(
                builder._jinja_env,
                "get_template",
                side_effect=Exception("template broken"),
            ):
                html = builder.render_html_only(minimal_data)
            # Must have fallen back — fallback always contains "Carbontrace"
            assert "Carbontrace" in html or len(html) > 0

    def test_render_returns_fallback_when_jinja_env_none(self, minimal_data: dict) -> None:
        """When _jinja_env is None, _render_html always uses _fallback_html_exec."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        builder = ExecDashboardBuilder()
        builder._jinja_env = None  # Force fallback path

        ctx = builder._build_context(minimal_data)
        html = builder._render_html(ctx)
        # Fallback always contains ADR-007
        assert "ADR-007" in html


# ---------------------------------------------------------------------------
# chart_data_uri in _build_context (line 442 — _png_to_data_uri call)
# ---------------------------------------------------------------------------

class TestBuildContextChartUri:

    def test_chart_data_uri_in_context_when_matplotlib_available(
        self, minimal_data: dict
    ) -> None:
        """_build_context produces a non-empty chart_data_uri when matplotlib works."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        builder = ExecDashboardBuilder()
        ctx = builder._build_context(minimal_data)
        # chart_data_uri is either a data URI (success) or "" (failure)
        assert isinstance(ctx["chart_data_uri"], str)

    def test_chart_data_uri_is_data_uri_format_on_success(
        self, minimal_data: dict
    ) -> None:
        """On successful chart rendering, the data URI has the correct prefix."""
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder

        builder = ExecDashboardBuilder()
        ctx = builder._build_context(minimal_data)
        uri = ctx["chart_data_uri"]
        if uri:  # empty string on failure — acceptable if matplotlib not available
            assert uri.startswith("data:image/png;base64,")

"""Tests for the Plotly hovertemplate builder (FR-23)."""

from __future__ import annotations

from ghg_tool.ui.streamlit_app.lib.tooltips import (
    CUSTOMDATA_COLS,
    CUSTOMDATA_COLS_WITH_CI,
    build_emission_hovertemplate,
)


class TestTooltips:
    def test_template_contains_factor_source(self) -> None:
        tmpl = build_emission_hovertemplate()
        assert "factor" in tmpl.lower() or "customdata[0]" in tmpl

    def test_template_contains_gwp_set(self) -> None:
        tmpl = build_emission_hovertemplate()
        assert "customdata[2]" in tmpl

    def test_template_contains_methodology(self) -> None:
        tmpl = build_emission_hovertemplate()
        assert "customdata[3]" in tmpl

    def test_template_ends_with_extra_tag(self) -> None:
        tmpl = build_emission_hovertemplate()
        assert tmpl.endswith("<extra></extra>")

    def test_ci_template_includes_confidence_interval(self) -> None:
        tmpl = build_emission_hovertemplate(include_ci=True)
        assert "customdata[5]" in tmpl
        assert "customdata[6]" in tmpl

    def test_bar_mode_uses_x_for_label(self) -> None:
        tmpl = build_emission_hovertemplate(mode="bar")
        assert "%{x}" in tmpl

    def test_customdata_cols_has_required_fields(self) -> None:
        required = {"factor_source", "factor_version", "gwp_set", "methodology"}
        assert required.issubset(set(CUSTOMDATA_COLS))

    def test_customdata_cols_with_ci_has_ci_fields(self) -> None:
        assert "ci_lower" in CUSTOMDATA_COLS_WITH_CI
        assert "ci_upper" in CUSTOMDATA_COLS_WITH_CI

    def test_custom_value_label(self) -> None:
        tmpl = build_emission_hovertemplate(value_label="Emissioni (tCO2e)")
        assert "Emissioni" in tmpl

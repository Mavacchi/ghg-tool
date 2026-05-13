"""Tests for the Okabe-Ito palette module (NFR-22)."""

from __future__ import annotations

from ghg_tool.ui.streamlit_app.lib.palette import (
    BLACK,
    BLUE,
    BLUISH_GREEN,
    EXCEL_HEADER_FILL,
    OKABE_ITO,
    ORANGE,
    REDDISH_PURPLE,
    SKY_BLUE,
    VERMILION,
    YELLOW,
    plotly_qualitative,
    scope_color,
    severity_color,
)


class TestOkabeItoPalette:
    def test_eight_colours_defined(self) -> None:
        assert len(OKABE_ITO) == 8

    def test_all_hex_format(self) -> None:
        for colour in OKABE_ITO:
            assert colour.startswith("#")
            assert len(colour) == 7

    def test_no_pure_red_green_pair(self) -> None:
        """WCAG: no red/green only status pair — CRIT is vermilion, OK is bluish-green."""
        pure_red = "#FF0000"
        pure_green = "#00FF00"
        assert pure_red not in OKABE_ITO
        assert pure_green not in OKABE_ITO

    def test_named_constants_in_palette(self) -> None:
        for c in [BLACK, ORANGE, SKY_BLUE, BLUISH_GREEN,
                  YELLOW, BLUE, VERMILION, REDDISH_PURPLE]:
            assert c in OKABE_ITO

    def test_crit_colour_is_vermilion(self) -> None:
        assert severity_color("CRIT") == VERMILION

    def test_warn_colour_is_orange(self) -> None:
        assert severity_color("WARN") == ORANGE

    def test_info_colour_is_bluish_green(self) -> None:
        assert severity_color("INFO") == BLUISH_GREEN

    def test_unknown_severity_fallback(self) -> None:
        assert severity_color("UNKNOWN") == BLACK

    def test_scope_1_colour(self) -> None:
        assert scope_color(1) == VERMILION

    def test_scope_2_colour(self) -> None:
        assert scope_color(2) == BLUE

    def test_scope_3_colour(self) -> None:
        assert scope_color(3) == BLUISH_GREEN

    def test_unknown_scope_fallback(self) -> None:
        assert scope_color(99) == BLACK

    def test_plotly_qualitative_returns_list(self) -> None:
        result = plotly_qualitative()
        assert isinstance(result, list)
        assert len(result) == 8

    def test_excel_header_fill_format(self) -> None:
        # Openpyxl ARGB: 8 hex chars
        assert len(EXCEL_HEADER_FILL) == 8
        assert EXCEL_HEADER_FILL.upper() == EXCEL_HEADER_FILL

"""Tests for the VIANO 2025 reduced-operation banner (FR-24, MG-12)."""

from __future__ import annotations

from ghg_tool.ui.streamlit_app.lib.banner import (
    _BANNER_YEAR,
    _VIANO_SITE_CODES,
    should_show_viano_banner,
)


class TestShouldShowVianoBanner:
    def test_shows_for_2025_with_viano(self) -> None:
        assert should_show_viano_banner(2025, ["VIANO", "IANO"]) is True

    def test_shows_for_2025_with_viano_gargola(self) -> None:
        assert should_show_viano_banner(2025, ["VIANO_GARGOLA"]) is True

    def test_does_not_show_for_2024(self) -> None:
        assert should_show_viano_banner(2024, ["VIANO"]) is False

    def test_does_not_show_for_2025_without_viano(self) -> None:
        assert should_show_viano_banner(2025, ["IANO", "CASALGRANDE", "FIORANO"]) is False

    def test_shows_for_2025_no_sites_specified(self) -> None:
        """Conservative: assume VIANO is visible when sites list is None."""
        assert should_show_viano_banner(2025, None) is True

    def test_shows_for_2025_all_sites(self) -> None:
        all_sites = ["IANO", "VIANO", "VIANO_GARGOLA", "CASALGRANDE",
                     "FIORANO", "SASSUOLO", "FRASSINORO"]
        assert should_show_viano_banner(2025, all_sites) is True

    def test_banner_year_is_2025(self) -> None:
        assert _BANNER_YEAR == 2025

    def test_viano_site_codes_contain_expected(self) -> None:
        assert "VIANO" in _VIANO_SITE_CODES
        assert "VIANO_GARGOLA" in _VIANO_SITE_CODES

    def test_does_not_show_for_2026(self) -> None:
        assert should_show_viano_banner(2026, ["VIANO"]) is False

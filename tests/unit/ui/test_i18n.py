"""Tests for the i18n translation module (FR-33)."""

from __future__ import annotations

from ghg_tool.ui.streamlit_app.lib.i18n import _, supported_languages


class TestI18n:
    def test_it_translation_loads(self) -> None:
        # app_title is now parametric: the company name is injected at
        # render time via .format(company_name=...). See lib/constants.py.
        result = _("app_title", "it")
        assert "Strumento GHG" in result
        assert "{company_name}" in result
        rendered = result.format(company_name="Acme Tiles")
        assert "Acme Tiles" in rendered

    def test_en_translation_loads(self) -> None:
        result = _("app_title", "en")
        assert "GHG Tool" in result
        assert "{company_name}" in result
        rendered = result.format(company_name="Acme Tiles")
        assert "Acme Tiles" in rendered

    def test_viano_banner_it(self) -> None:
        text = _("viano_banner", "it")
        assert "VIANO" in text
        assert "2025" in text

    def test_viano_banner_en(self) -> None:
        text = _("viano_banner", "en")
        assert "VIANO" in text
        assert "2025" in text

    def test_missing_key_returns_key(self) -> None:
        result = _("nonexistent_key_xyz", "it")
        assert result == "nonexistent_key_xyz"

    def test_unsupported_lang_falls_back_to_it(self) -> None:
        result = _("app_title", "de")
        it_result = _("app_title", "it")
        assert result == it_result

    def test_supported_languages_contains_it_en(self) -> None:
        langs = supported_languages()
        assert "it" in langs
        assert "en" in langs

    def test_biogenic_adv007_it(self) -> None:
        text = _("biogenic_adv007", "it")
        assert "ADR-007" in text
        assert "E1-7" in text
        assert "biogenic" in text.lower() or "biogenich" in text.lower()

    def test_biogenic_adv007_en(self) -> None:
        text = _("biogenic_adv007", "en")
        assert "ADR-007" in text
        assert "E1-7" in text
        assert "iogenic" in text  # "biogenic" or "Biogenic"

    def test_intensity_endpoint_missing_message(self) -> None:
        msg = _("intensity_endpoint_missing", "en")
        assert "intensity" in msg.lower()
        assert "BackendAgent" in msg

    def test_default_lang_is_it(self) -> None:
        result_default = _("nav_home")
        result_it = _("nav_home", "it")
        assert result_default == result_it

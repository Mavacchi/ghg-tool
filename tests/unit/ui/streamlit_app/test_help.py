"""Unit tests for ghg_tool.ui.streamlit_app.lib.help.

No Streamlit runtime — ``help.py`` has no ``st`` dependency.
Tests verify the glossary loader and the ``_help`` public helper.
"""

from __future__ import annotations

import json

import ghg_tool.ui.streamlit_app.lib.help as help_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_cache() -> None:
    """Empty the module-level glossary cache between tests."""
    help_mod._CACHE.clear()


# ---------------------------------------------------------------------------
# _load
# ---------------------------------------------------------------------------


class TestLoad:
    def setup_method(self):
        _clear_cache()

    def teardown_method(self):
        _clear_cache()

    def test_loads_glossary_for_supported_lang(self, tmp_path, monkeypatch):
        glossary = {"scope1": "Scope 1 definition"}
        (tmp_path / "glossary_en.json").write_text(json.dumps(glossary), encoding="utf-8")
        monkeypatch.setattr(help_mod, "_GLOSSARY_DIR", tmp_path)

        result = help_mod._load("en")

        assert result["scope1"] == "Scope 1 definition"

    def test_caches_result_on_second_call(self, tmp_path, monkeypatch):
        glossary = {"key": "value"}
        (tmp_path / "glossary_it.json").write_text(json.dumps(glossary), encoding="utf-8")
        monkeypatch.setattr(help_mod, "_GLOSSARY_DIR", tmp_path)

        result1 = help_mod._load("it")
        # Overwrite file — second call must return cached dict, not re-read.
        (tmp_path / "glossary_it.json").write_text(json.dumps({"key": "changed"}), encoding="utf-8")
        result2 = help_mod._load("it")

        assert result2 is result1
        assert result2["key"] == "value"

    def test_falls_back_to_it_when_lang_file_missing(self, tmp_path, monkeypatch):
        it_glossary = {"scope2": "Scope 2 IT"}
        (tmp_path / "glossary_it.json").write_text(json.dumps(it_glossary), encoding="utf-8")
        monkeypatch.setattr(help_mod, "_GLOSSARY_DIR", tmp_path)

        # "fr" has no file → falls back to IT.
        result = help_mod._load("fr")

        assert result["scope2"] == "Scope 2 IT"

    def test_returns_dict(self, tmp_path, monkeypatch):
        (tmp_path / "glossary_it.json").write_text(json.dumps({}), encoding="utf-8")
        monkeypatch.setattr(help_mod, "_GLOSSARY_DIR", tmp_path)

        result = help_mod._load("it")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _help
# ---------------------------------------------------------------------------


class TestHelpFunction:
    def setup_method(self):
        _clear_cache()

    def teardown_method(self):
        _clear_cache()

    def test_returns_string_for_known_key(self, tmp_path, monkeypatch):
        glossary = {"scope1": "Emissioni dirette"}
        (tmp_path / "glossary_it.json").write_text(json.dumps(glossary), encoding="utf-8")
        monkeypatch.setattr(help_mod, "_GLOSSARY_DIR", tmp_path)

        result = help_mod._help("scope1", "it")

        assert result == "Emissioni dirette"

    def test_returns_none_for_unknown_key(self, tmp_path, monkeypatch):
        (tmp_path / "glossary_it.json").write_text(json.dumps({"scope1": "x"}), encoding="utf-8")
        monkeypatch.setattr(help_mod, "_GLOSSARY_DIR", tmp_path)

        result = help_mod._help("nonexistent_key", "it")

        assert result is None

    def test_defaults_to_it_when_no_lang_given(self, tmp_path, monkeypatch):
        it_glossary = {"gwp": "GWP IT def"}
        en_glossary = {"gwp": "GWP EN def"}
        (tmp_path / "glossary_it.json").write_text(json.dumps(it_glossary), encoding="utf-8")
        (tmp_path / "glossary_en.json").write_text(json.dumps(en_glossary), encoding="utf-8")
        monkeypatch.setattr(help_mod, "_GLOSSARY_DIR", tmp_path)

        result = help_mod._help("gwp")

        assert result == "GWP IT def"

    def test_resolves_unsupported_lang_to_default_it(self, tmp_path, monkeypatch):
        it_glossary = {"tco2e": "Tonnellate CO2e"}
        (tmp_path / "glossary_it.json").write_text(json.dumps(it_glossary), encoding="utf-8")
        monkeypatch.setattr(help_mod, "_GLOSSARY_DIR", tmp_path)

        result = help_mod._help("tco2e", "zh")

        assert result == "Tonnellate CO2e"

    def test_returns_english_string_for_en_lang(self, tmp_path, monkeypatch):
        en_glossary = {"gwp": "GWP AR6 English description"}
        (tmp_path / "glossary_en.json").write_text(json.dumps(en_glossary), encoding="utf-8")
        monkeypatch.setattr(help_mod, "_GLOSSARY_DIR", tmp_path)

        result = help_mod._help("gwp", "en")

        assert result == "GWP AR6 English description"

    def test_returns_none_not_empty_string_for_missing_key(self, tmp_path, monkeypatch):
        """Streamlit hides the help icon when the value is None; empty string is wrong."""
        (tmp_path / "glossary_it.json").write_text(json.dumps({}), encoding="utf-8")
        monkeypatch.setattr(help_mod, "_GLOSSARY_DIR", tmp_path)

        result = help_mod._help("missing")

        assert result is None

    def test_works_with_real_glossary_file(self):
        """Smoke test: the real bundled glossary files are present and loadable."""
        result = help_mod._help("scope1", "it")
        # The real file contains a long definition — just check it's a non-empty string.
        assert isinstance(result, str)
        assert len(result) > 10

    def test_real_en_glossary_loadable(self):
        result = help_mod._help("gwp", "en")
        assert result is None or isinstance(result, str)

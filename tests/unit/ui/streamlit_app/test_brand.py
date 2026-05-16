"""Unit tests for ghg_tool.ui.streamlit_app.lib.brand.

Mocks ``streamlit`` entirely — no Streamlit runtime required.
All brand functions are tested by injecting a MagicMock for ``st``
and asserting call signatures on its methods.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_st_mock(session_state: dict | None = None) -> MagicMock:
    """Return a minimal streamlit mock with a dict-backed session_state."""
    mock_st = MagicMock()
    mock_st.session_state = session_state if session_state is not None else {}
    mock_st.sidebar = MagicMock()
    return mock_st


# ---------------------------------------------------------------------------
# _brand_css
# ---------------------------------------------------------------------------


class TestBrandCss:
    """Tests for the private _brand_css() cached reader."""

    def test_returns_css_when_file_exists(self, tmp_path, monkeypatch):
        css_file = tmp_path / "brand.css"
        css_file.write_text("body { color: red; }", encoding="utf-8")

        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        monkeypatch.setattr(brand_mod, "_BRAND_CSS_PATH", css_file)
        # Clear lru_cache so our patched path is picked up.
        brand_mod._brand_css.cache_clear()
        result = brand_mod._brand_css()
        assert result == "body { color: red; }"
        brand_mod._brand_css.cache_clear()

    def test_returns_empty_string_when_file_missing(self, tmp_path, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        monkeypatch.setattr(brand_mod, "_BRAND_CSS_PATH", tmp_path / "nonexistent.css")
        brand_mod._brand_css.cache_clear()
        result = brand_mod._brand_css()
        assert result == ""
        brand_mod._brand_css.cache_clear()


# ---------------------------------------------------------------------------
# _inject_css
# ---------------------------------------------------------------------------


class TestInjectCss:
    def test_injects_style_tag_when_css_nonempty(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)
        monkeypatch.setattr(brand_mod, "_brand_css", lambda: "h1{color:blue}")

        brand_mod._inject_css()

        mock_st.markdown.assert_called_once()
        call_args = mock_st.markdown.call_args
        assert "<style>" in call_args.args[0]
        assert call_args.kwargs.get("unsafe_allow_html") is True

    def test_no_markdown_call_when_css_empty(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)
        monkeypatch.setattr(brand_mod, "_brand_css", lambda: "")

        brand_mod._inject_css()

        mock_st.markdown.assert_not_called()


# ---------------------------------------------------------------------------
# _register_logo
# ---------------------------------------------------------------------------


class TestRegisterLogo:
    def test_calls_st_logo_when_logo_exists(self, tmp_path, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        logo = tmp_path / "logo.png"
        logo.write_bytes(b"PNG")

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)
        monkeypatch.setattr(brand_mod, "LOGO_PATH", logo)
        monkeypatch.setattr(brand_mod, "LOGO_COLLAPSED_PATH", tmp_path / "nofile.png")
        monkeypatch.setattr(brand_mod, "FAVICON_PATH", tmp_path / "nofile2.png")

        brand_mod._register_logo()

        mock_st.logo.assert_called_once_with(str(logo), icon_image=None)

    def test_uses_collapsed_logo_as_icon_when_present(self, tmp_path, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        logo = tmp_path / "logo.png"
        logo.write_bytes(b"PNG")
        collapsed = tmp_path / "logo_collapsed.png"
        collapsed.write_bytes(b"PNG2")

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)
        monkeypatch.setattr(brand_mod, "LOGO_PATH", logo)
        monkeypatch.setattr(brand_mod, "LOGO_COLLAPSED_PATH", collapsed)
        monkeypatch.setattr(brand_mod, "FAVICON_PATH", tmp_path / "nofile.png")

        brand_mod._register_logo()

        mock_st.logo.assert_called_once_with(str(logo), icon_image=str(collapsed))

    def test_uses_favicon_as_icon_when_collapsed_missing(self, tmp_path, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        logo = tmp_path / "logo.png"
        logo.write_bytes(b"PNG")
        favicon = tmp_path / "favicon.png"
        favicon.write_bytes(b"ICO")

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)
        monkeypatch.setattr(brand_mod, "LOGO_PATH", logo)
        monkeypatch.setattr(brand_mod, "LOGO_COLLAPSED_PATH", tmp_path / "nofile.png")
        monkeypatch.setattr(brand_mod, "FAVICON_PATH", favicon)

        brand_mod._register_logo()

        mock_st.logo.assert_called_once_with(str(logo), icon_image=str(favicon))

    def test_skips_when_logo_path_missing(self, tmp_path, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)
        monkeypatch.setattr(brand_mod, "LOGO_PATH", tmp_path / "missing.png")

        brand_mod._register_logo()

        mock_st.logo.assert_not_called()

    def test_skips_when_st_has_no_logo_attribute(self, tmp_path, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        logo = tmp_path / "logo.png"
        logo.write_bytes(b"PNG")

        mock_st = MagicMock(spec=[])  # no attributes in spec → hasattr returns False
        monkeypatch.setattr(brand_mod, "st", mock_st)
        monkeypatch.setattr(brand_mod, "LOGO_PATH", logo)

        brand_mod._register_logo()
        # logo was not called since spec=[] omits it
        assert not hasattr(mock_st, "logo") or not mock_st.logo.called


# ---------------------------------------------------------------------------
# _render_skip_link
# ---------------------------------------------------------------------------


class TestRenderSkipLink:
    def test_italian_label(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)

        brand_mod._render_skip_link("it")

        html = mock_st.markdown.call_args.args[0]
        assert "Salta al contenuto" in html
        assert mock_st.markdown.call_args.kwargs.get("unsafe_allow_html") is True

    def test_english_label(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)

        brand_mod._render_skip_link("en")

        html = mock_st.markdown.call_args.args[0]
        assert "Skip to main content" in html

    def test_unknown_lang_falls_back_to_english_label(self, monkeypatch):
        """Any lang that is not 'it' produces the English label."""
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)

        brand_mod._render_skip_link("fr")

        html = mock_st.markdown.call_args.args[0]
        assert "Skip to main content" in html


# ---------------------------------------------------------------------------
# render_context_bar
# ---------------------------------------------------------------------------


class TestRenderContextBar:
    def test_renders_all_three_parts(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)

        brand_mod.render_context_bar(lang="en", year=2025, gwp="AR6", role="admin")

        mock_st.markdown.assert_called_once()
        html = mock_st.markdown.call_args.args[0]
        assert "2025" in html
        assert "AR6" in html
        assert "admin" in html

    def test_renders_nothing_when_all_omitted(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)

        brand_mod.render_context_bar(lang="it")

        mock_st.markdown.assert_not_called()

    def test_italian_labels(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)

        brand_mod.render_context_bar(lang="it", year=2024, gwp="AR5", role="viewer")

        html = mock_st.markdown.call_args.args[0]
        assert "Anno" in html
        assert "Ruolo" in html

    def test_year_zero_is_rendered(self, monkeypatch):
        """year=0 is not None so it must appear in the output."""
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)

        brand_mod.render_context_bar(lang="en", year=0)

        html = mock_st.markdown.call_args.args[0]
        assert ">0<" in html

    def test_empty_gwp_string_is_skipped(self, monkeypatch):
        """Empty string is falsy; gwp part should not appear."""
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)

        brand_mod.render_context_bar(lang="en", gwp="")

        mock_st.markdown.assert_not_called()

    def test_separator_present_between_multiple_parts(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)

        brand_mod.render_context_bar(lang="en", year=2025, gwp="AR6")

        html = mock_st.markdown.call_args.args[0]
        assert "ct-ctx-sep" in html


# ---------------------------------------------------------------------------
# render_role_chip
# ---------------------------------------------------------------------------


class TestRenderRoleChip:
    @pytest.mark.parametrize("role,lang,expected_label", [
        ("viewer", "it", "Sola lettura"),
        ("viewer", "en", "Read-only"),
        ("editor", "it", "Modifica dati"),
        ("editor", "en", "Editor"),
        ("admin", "it", "Amministratore"),
        ("admin", "en", "Administrator"),
    ])
    def test_known_roles_produce_correct_label(self, role, lang, expected_label, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)

        brand_mod.render_role_chip(role=role, lang=lang)

        mock_st.sidebar.markdown.assert_called_once()
        html = mock_st.sidebar.markdown.call_args.args[0]
        assert expected_label in html

    def test_none_role_does_not_render(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)

        brand_mod.render_role_chip(role=None)

        mock_st.sidebar.markdown.assert_not_called()

    def test_unknown_role_does_not_render(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)

        brand_mod.render_role_chip(role="superuser")

        mock_st.sidebar.markdown.assert_not_called()

    def test_unsupported_lang_falls_back_to_it(self, monkeypatch):
        """An unrecognised lang should still render using the Italian label."""
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)

        brand_mod.render_role_chip(role="admin", lang="fr")

        html = mock_st.sidebar.markdown.call_args.args[0]
        assert "Amministratore" in html

    def test_html_contains_data_role_attribute(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)

        brand_mod.render_role_chip(role="editor", lang="en")

        html = mock_st.sidebar.markdown.call_args.args[0]
        assert 'data-role="editor"' in html

    def test_caption_included_in_html(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock()
        monkeypatch.setattr(brand_mod, "st", mock_st)

        brand_mod.render_role_chip(role="viewer", lang="en")

        html = mock_st.sidebar.markdown.call_args.args[0]
        assert "ct-role-caption" in html
        assert "view" in html.lower()


# ---------------------------------------------------------------------------
# apply_brand_chrome
# ---------------------------------------------------------------------------


class TestApplyBrandChrome:
    def test_reads_lang_from_session_state_when_not_provided(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock(session_state={"lang": "en"})
        monkeypatch.setattr(brand_mod, "st", mock_st)
        monkeypatch.setattr(brand_mod, "_register_logo", MagicMock())
        monkeypatch.setattr(brand_mod, "_inject_css", MagicMock())

        called_with = []

        def fake_skip_link(lang):
            called_with.append(lang)

        monkeypatch.setattr(brand_mod, "_render_skip_link", fake_skip_link)

        brand_mod.apply_brand_chrome()

        assert called_with == ["en"]

    def test_falls_back_to_it_when_lang_absent_from_session(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock(session_state={})
        monkeypatch.setattr(brand_mod, "st", mock_st)
        monkeypatch.setattr(brand_mod, "_register_logo", MagicMock())
        monkeypatch.setattr(brand_mod, "_inject_css", MagicMock())

        called_with = []
        monkeypatch.setattr(brand_mod, "_render_skip_link", lambda lang: called_with.append(lang))

        brand_mod.apply_brand_chrome()

        assert called_with == ["it"]

    def test_explicit_lang_overrides_session_state(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock(session_state={"lang": "it"})
        monkeypatch.setattr(brand_mod, "st", mock_st)
        monkeypatch.setattr(brand_mod, "_register_logo", MagicMock())
        monkeypatch.setattr(brand_mod, "_inject_css", MagicMock())

        called_with = []
        monkeypatch.setattr(brand_mod, "_render_skip_link", lambda lang: called_with.append(lang))

        brand_mod.apply_brand_chrome(lang="en")

        assert called_with == ["en"]

    def test_calls_all_three_sub_helpers(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.brand as brand_mod

        mock_st = _make_st_mock(session_state={})
        monkeypatch.setattr(brand_mod, "st", mock_st)

        reg = MagicMock()
        inj = MagicMock()
        skip = MagicMock()
        monkeypatch.setattr(brand_mod, "_register_logo", reg)
        monkeypatch.setattr(brand_mod, "_inject_css", inj)
        monkeypatch.setattr(brand_mod, "_render_skip_link", skip)

        brand_mod.apply_brand_chrome(lang="it")

        reg.assert_called_once()
        inj.assert_called_once()
        skip.assert_called_once_with("it")

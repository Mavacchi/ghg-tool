"""Unit tests for ghg_tool.ui.streamlit_app.lib.filters.

Mocks ``streamlit`` and the ``_help`` / ``_`` helpers entirely.
No Streamlit runtime, no network, no DB.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Module-level streamlit mock applied before first import of filters.
# We patch at the sys.modules level so that `import streamlit as st` inside
# the module under test resolves to our mock.
# ---------------------------------------------------------------------------


def _fresh_filters(session_state: dict | None = None):
    """Import filters module with a clean st mock injected."""
    import sys

    state = session_state if session_state is not None else {}

    st_mock = MagicMock()
    st_mock.session_state = state
    st_mock.query_params = {}

    # Pop cached copies so re-import picks up our mock.
    for key in list(sys.modules):
        if "ghg_tool.ui.streamlit_app.lib.filters" in key:
            del sys.modules[key]

    with patch.dict(sys.modules, {"streamlit": st_mock}):
        import ghg_tool.ui.streamlit_app.lib.filters as f
        return f, st_mock, state


# ---------------------------------------------------------------------------
# available_years
# ---------------------------------------------------------------------------


class TestAvailableYears:
    def test_returns_list_of_ints(self):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        years = f.available_years()
        assert isinstance(years, list)
        assert all(isinstance(y, int) for y in years)

    def test_returns_copy_not_reference(self):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        y1 = f.available_years()
        y2 = f.available_years()
        assert y1 is not y2

    def test_contains_expected_range(self):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        years = f.available_years()
        assert 2024 in years
        assert 2026 in years


# ---------------------------------------------------------------------------
# _default_year
# ---------------------------------------------------------------------------


class TestDefaultYear:
    def test_returns_current_year_when_in_options(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        # Freeze today to a year that is in _YEAR_OPTIONS (2025).
        monkeypatch.setattr(f._dt, "date", MagicMock(
            today=MagicMock(return_value=MagicMock(year=2025))
        ))
        # Ensure _YEAR_OPTIONS contains 2025.
        monkeypatch.setattr(f, "_YEAR_OPTIONS", [2024, 2025, 2026])
        assert f._default_year() == 2025

    def test_falls_back_to_last_option_when_current_not_in_list(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        monkeypatch.setattr(f._dt, "date", MagicMock(
            today=MagicMock(return_value=MagicMock(year=2099))
        ))
        monkeypatch.setattr(f, "_YEAR_OPTIONS", [2024, 2025, 2026])
        assert f._default_year() == 2026


# ---------------------------------------------------------------------------
# current_year
# ---------------------------------------------------------------------------


class TestCurrentYear:
    def test_returns_session_value_when_valid(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        mock_st = MagicMock()
        mock_st.session_state = {"g_year": 2025}
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_YEAR_OPTIONS", [2024, 2025, 2026])

        assert f.current_year() == 2025

    def test_returns_default_when_key_missing(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        mock_st = MagicMock()
        mock_st.session_state = {}
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_YEAR_OPTIONS", [2024, 2025, 2026])
        monkeypatch.setattr(f, "_default_year", lambda: 2026)

        assert f.current_year() == 2026

    def test_returns_default_when_year_not_in_options(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        mock_st = MagicMock()
        mock_st.session_state = {"g_year": 2099}
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_YEAR_OPTIONS", [2024, 2025, 2026])
        monkeypatch.setattr(f, "_default_year", lambda: 2024)

        assert f.current_year() == 2024

    def test_returns_default_when_value_is_string(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        mock_st = MagicMock()
        mock_st.session_state = {"g_year": "2025"}
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_YEAR_OPTIONS", [2024, 2025, 2026])
        monkeypatch.setattr(f, "_default_year", lambda: 2024)

        # string is not int → should fall through to default
        assert f.current_year() == 2024


# ---------------------------------------------------------------------------
# current_gwp
# ---------------------------------------------------------------------------


class TestCurrentGwp:
    def test_returns_session_value_when_valid(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        mock_st = MagicMock()
        mock_st.session_state = {"g_gwp": "AR5"}
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_GWP_OPTIONS", ["AR6", "AR5"])

        assert f.current_gwp() == "AR5"

    def test_returns_first_option_when_key_missing(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        mock_st = MagicMock()
        mock_st.session_state = {}
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_GWP_OPTIONS", ["AR6", "AR5"])

        assert f.current_gwp() == "AR6"

    def test_returns_first_option_when_value_not_in_options(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        mock_st = MagicMock()
        mock_st.session_state = {"g_gwp": "AR4"}
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_GWP_OPTIONS", ["AR6", "AR5"])

        assert f.current_gwp() == "AR6"

    def test_returns_first_option_when_value_is_int(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        mock_st = MagicMock()
        mock_st.session_state = {"g_gwp": 6}  # wrong type
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_GWP_OPTIONS", ["AR6", "AR5"])

        assert f.current_gwp() == "AR6"


# ---------------------------------------------------------------------------
# _read_query_params_into_state
# ---------------------------------------------------------------------------


class TestReadQueryParamsIntoState:
    def test_hydrates_year_from_valid_query_param(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        state: dict = {}
        mock_st = MagicMock()
        mock_st.session_state = state
        mock_st.query_params = {"y": "2025"}
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_YEAR_OPTIONS", [2024, 2025, 2026])
        monkeypatch.setattr(f, "_GWP_OPTIONS", ["AR6", "AR5"])

        f._read_query_params_into_state()

        assert state.get("g_year") == 2025

    def test_hydrates_gwp_from_valid_query_param(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        state: dict = {}
        mock_st = MagicMock()
        mock_st.session_state = state
        mock_st.query_params = {"g": "AR5"}
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_GWP_OPTIONS", ["AR6", "AR5"])
        monkeypatch.setattr(f, "_YEAR_OPTIONS", [2024, 2025, 2026])

        f._read_query_params_into_state()

        assert state.get("g_gwp") == "AR5"

    def test_does_not_override_existing_year(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        state: dict = {"g_year": 2024}
        mock_st = MagicMock()
        mock_st.session_state = state
        mock_st.query_params = {"y": "2026"}
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_YEAR_OPTIONS", [2024, 2025, 2026])

        f._read_query_params_into_state()

        assert state["g_year"] == 2024  # untouched

    def test_ignores_invalid_year_string(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        state: dict = {}
        mock_st = MagicMock()
        mock_st.session_state = state
        mock_st.query_params = {"y": "not_a_number"}
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_YEAR_OPTIONS", [2024, 2025, 2026])

        f._read_query_params_into_state()

        assert "g_year" not in state

    def test_ignores_year_outside_options(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        state: dict = {}
        mock_st = MagicMock()
        mock_st.session_state = state
        mock_st.query_params = {"y": "2099"}
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_YEAR_OPTIONS", [2024, 2025, 2026])

        f._read_query_params_into_state()

        assert "g_year" not in state

    def test_ignores_gwp_not_in_options(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        state: dict = {}
        mock_st = MagicMock()
        mock_st.session_state = state
        mock_st.query_params = {"g": "AR4"}
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_GWP_OPTIONS", ["AR6", "AR5"])
        monkeypatch.setattr(f, "_YEAR_OPTIONS", [2024, 2025, 2026])

        f._read_query_params_into_state()

        assert "g_gwp" not in state

    def test_skips_gracefully_when_query_params_raises_attribute_error(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        mock_st = MagicMock(spec=["session_state"])
        mock_st.session_state = {}
        # Accessing .query_params will raise AttributeError because it's not in spec
        monkeypatch.setattr(f, "st", mock_st)

        # Should not raise
        f._read_query_params_into_state()


# ---------------------------------------------------------------------------
# _sync_query_params_from_state
# ---------------------------------------------------------------------------


class TestSyncQueryParamsFromState:
    def test_writes_year_and_gwp_to_query_params(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        qp: dict = {}
        mock_st = MagicMock()
        mock_st.session_state = {"g_year": 2025, "g_gwp": "AR6"}
        mock_st.query_params = qp
        monkeypatch.setattr(f, "st", mock_st)

        f._sync_query_params_from_state()

        assert qp.get("y") == "2025"
        assert qp.get("g") == "AR6"

    def test_does_not_write_when_values_absent(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        qp: dict = {}
        mock_st = MagicMock()
        mock_st.session_state = {}
        mock_st.query_params = qp
        monkeypatch.setattr(f, "st", mock_st)

        f._sync_query_params_from_state()

        assert qp == {}

    def test_skips_gracefully_when_query_params_raises_attribute_error(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        mock_st = MagicMock(spec=["session_state"])
        mock_st.session_state = {"g_year": 2025}
        monkeypatch.setattr(f, "st", mock_st)

        # Should not raise
        f._sync_query_params_from_state()


# ---------------------------------------------------------------------------
# sidebar_year_filter
# ---------------------------------------------------------------------------


class TestSidebarYearFilter:
    def test_calls_selectbox_and_returns_value(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        state: dict = {}
        mock_st = MagicMock()
        mock_st.session_state = state
        mock_st.query_params = {}
        mock_st.selectbox.return_value = 2025
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_YEAR_OPTIONS", [2024, 2025, 2026])
        monkeypatch.setattr(f, "_default_year", lambda: 2025)
        monkeypatch.setattr(f, "_read_query_params_into_state", MagicMock())
        monkeypatch.setattr(f, "_sync_query_params_from_state", MagicMock())

        result = f.sidebar_year_filter("en")

        mock_st.selectbox.assert_called_once()
        assert result == 2025

    def test_initialises_default_in_session_when_key_absent(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        state: dict = {}
        mock_st = MagicMock()
        mock_st.session_state = state
        mock_st.query_params = {}
        mock_st.selectbox.return_value = 2024
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_YEAR_OPTIONS", [2024, 2025, 2026])
        monkeypatch.setattr(f, "_default_year", lambda: 2024)
        monkeypatch.setattr(f, "_read_query_params_into_state", MagicMock())
        monkeypatch.setattr(f, "_sync_query_params_from_state", MagicMock())

        f.sidebar_year_filter("it")

        assert state.get("g_year") == 2024

    def test_does_not_overwrite_existing_year_in_session(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        state: dict = {"g_year": 2026}
        mock_st = MagicMock()
        mock_st.session_state = state
        mock_st.query_params = {}
        mock_st.selectbox.return_value = 2026
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_YEAR_OPTIONS", [2024, 2025, 2026])
        monkeypatch.setattr(f, "_default_year", lambda: 2024)
        monkeypatch.setattr(f, "_read_query_params_into_state", MagicMock())
        monkeypatch.setattr(f, "_sync_query_params_from_state", MagicMock())

        f.sidebar_year_filter("it")

        assert state["g_year"] == 2026  # untouched by the function


# ---------------------------------------------------------------------------
# sidebar_gwp_filter
# ---------------------------------------------------------------------------


class TestSidebarGwpFilter:
    def test_calls_selectbox_and_returns_value(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        state: dict = {}
        mock_st = MagicMock()
        mock_st.session_state = state
        mock_st.query_params = {}
        mock_st.selectbox.return_value = "AR6"
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_GWP_OPTIONS", ["AR6", "AR5"])
        monkeypatch.setattr(f, "_read_query_params_into_state", MagicMock())
        monkeypatch.setattr(f, "_sync_query_params_from_state", MagicMock())

        result = f.sidebar_gwp_filter("en")

        mock_st.selectbox.assert_called_once()
        assert result == "AR6"

    def test_initialises_default_gwp_in_session_when_key_absent(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        state: dict = {}
        mock_st = MagicMock()
        mock_st.session_state = state
        mock_st.query_params = {}
        mock_st.selectbox.return_value = "AR6"
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_GWP_OPTIONS", ["AR6", "AR5"])
        monkeypatch.setattr(f, "_read_query_params_into_state", MagicMock())
        monkeypatch.setattr(f, "_sync_query_params_from_state", MagicMock())

        f.sidebar_gwp_filter("it")

        assert state.get("g_gwp") == "AR6"

    def test_does_not_overwrite_existing_gwp_in_session(self, monkeypatch):
        import ghg_tool.ui.streamlit_app.lib.filters as f

        state: dict = {"g_gwp": "AR5"}
        mock_st = MagicMock()
        mock_st.session_state = state
        mock_st.query_params = {}
        mock_st.selectbox.return_value = "AR5"
        monkeypatch.setattr(f, "st", mock_st)
        monkeypatch.setattr(f, "_GWP_OPTIONS", ["AR6", "AR5"])
        monkeypatch.setattr(f, "_read_query_params_into_state", MagicMock())
        monkeypatch.setattr(f, "_sync_query_params_from_state", MagicMock())

        f.sidebar_gwp_filter("it")

        assert state["g_gwp"] == "AR5"

"""Unit tests for the demo-mode environment gate (BUG-23 / S-011).

Verifies that ``GHG_DEMO_MODE=true`` is only honoured when
``GHG_ENVIRONMENT`` is ``development`` or ``test``.  In production or
staging the flag must be suppressed and a CRITICAL log line emitted.

The module-level constants in ``lib.auth`` are evaluated at import time, so
each test reloads the module after patching the relevant env vars via
``importlib.reload`` and ``unittest.mock.patch.dict``.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from unittest.mock import patch  # noqa: F401 used in body

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_auth_module(env_overrides: dict[str, str]) -> object:
    """Reload ``ghg_tool.ui.streamlit_app.lib.auth`` with patched env vars.

    Args:
        env_overrides: Dict of env-var names to values to inject.

    Returns:
        The freshly reloaded module object.
    """
    module_name = "ghg_tool.ui.streamlit_app.lib.auth"
    # Remove the cached module so the next import re-executes module-level code.
    sys.modules.pop(module_name, None)

    # Also remove sub-dependencies that may have been cached with stale state.
    for key in list(sys.modules.keys()):
        if key.startswith("ghg_tool.ui.streamlit_app.lib.auth"):
            sys.modules.pop(key, None)

    # Patch env before import so _DEMO_MODE_REQUESTED is re-evaluated.
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("GHG_DEMO_MODE", "GHG_ENVIRONMENT")
    }
    clean_env.update(env_overrides)

    with patch.dict(os.environ, clean_env, clear=True):
        # Use importlib to force re-execution of module-level code.
        import ghg_tool.ui.streamlit_app.lib.auth as auth_mod

        importlib.reload(auth_mod)
        return auth_mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDemoModeGate:
    def test_demo_enabled_in_development(self) -> None:
        """DEMO_MODE=true + ENVIRONMENT=development -> _DEMO_MODE is True."""
        mod = _reload_auth_module(
            {"GHG_DEMO_MODE": "true", "GHG_ENVIRONMENT": "development"}
        )
        assert mod._DEMO_MODE is True

    def test_demo_enabled_in_test(self) -> None:
        """DEMO_MODE=true + ENVIRONMENT=test -> _DEMO_MODE is True."""
        mod = _reload_auth_module(
            {"GHG_DEMO_MODE": "true", "GHG_ENVIRONMENT": "test"}
        )
        assert mod._DEMO_MODE is True

    def test_demo_blocked_in_production(self, caplog: object) -> None:
        """DEMO_MODE=true + ENVIRONMENT=production -> _DEMO_MODE is False."""
        with patch.dict(
            os.environ,
            {"GHG_DEMO_MODE": "true", "GHG_ENVIRONMENT": "production"},
            clear=False,
        ):
            sys.modules.pop("ghg_tool.ui.streamlit_app.lib.auth", None)
            import ghg_tool.ui.streamlit_app.lib.auth as auth_mod
            importlib.reload(auth_mod)

        assert auth_mod._DEMO_MODE is False

    def test_demo_blocked_in_staging(self) -> None:
        """DEMO_MODE=true + ENVIRONMENT=staging -> _DEMO_MODE is False."""
        with patch.dict(
            os.environ,
            {"GHG_DEMO_MODE": "true", "GHG_ENVIRONMENT": "staging"},
            clear=False,
        ):
            sys.modules.pop("ghg_tool.ui.streamlit_app.lib.auth", None)
            import ghg_tool.ui.streamlit_app.lib.auth as auth_mod
            importlib.reload(auth_mod)

        assert auth_mod._DEMO_MODE is False

    def test_demo_disabled_when_flag_not_set(self) -> None:
        """GHG_DEMO_MODE not set -> _DEMO_MODE is False regardless of env."""
        with patch.dict(
            os.environ,
            {"GHG_ENVIRONMENT": "development"},
            clear=False,
        ):
            # Remove the flag entirely.
            os.environ.pop("GHG_DEMO_MODE", None)
            sys.modules.pop("ghg_tool.ui.streamlit_app.lib.auth", None)
            import ghg_tool.ui.streamlit_app.lib.auth as auth_mod
            importlib.reload(auth_mod)

        assert auth_mod._DEMO_MODE is False

    def test_critical_log_emitted_when_blocked(self) -> None:
        """When demo is blocked, a CRITICAL log line must be emitted at module load."""
        import logging

        # Capture log records from the auth module logger.
        logger_name = "ghg_tool.ui.streamlit_app.lib.auth"
        with patch.dict(
            os.environ,
            {"GHG_DEMO_MODE": "true", "GHG_ENVIRONMENT": "production"},
            clear=False,
        ):
            sys.modules.pop(logger_name, None)
            sys.modules.pop("ghg_tool.ui.streamlit_app.lib.auth", None)

            with self._CaptureLog(logger_name, logging.CRITICAL) as records:
                import ghg_tool.ui.streamlit_app.lib.auth as auth_mod
                importlib.reload(auth_mod)

        assert auth_mod._DEMO_MODE is False
        # At least one CRITICAL record must mention demo_mode_blocked_outside_dev.
        messages = [r.getMessage() for r in records]
        assert any("demo_mode_blocked_outside_dev" in m for m in messages), (
            f"Expected CRITICAL log with event=demo_mode_blocked_outside_dev; got: {messages}"
        )

    class _CaptureLog:
        """Context manager that collects log records at or above a given level."""

        def __init__(self, logger_name: str, level: int) -> None:
            self._logger_name = logger_name
            self._level = level
            self._records: list[logging.LogRecord] = []

        def __enter__(self) -> list[logging.LogRecord]:
            records = self._records

            class _CapturingHandler(logging.Handler):
                def emit(self, record: logging.LogRecord) -> None:
                    records.append(record)

            self._handler = _CapturingHandler(self._level)
            logging.getLogger(self._logger_name).addHandler(self._handler)
            logging.getLogger(self._logger_name).setLevel(self._level)
            return self._records

        def __exit__(self, *_: object) -> None:
            logging.getLogger(self._logger_name).removeHandler(self._handler)

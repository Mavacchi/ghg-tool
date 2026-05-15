"""UI unit-test conftest.

Clears the i18n translation cache before every test so that the module-level
_CACHE dict (populated on first import) does not persist stale entries when
the installed package path differs from the worktree src path.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_i18n_cache() -> None:
    """Reset the i18n translation cache before each test.

    The i18n module caches translations at module level.  When the API
    package is imported early (e.g. from test_exports_router), Python may
    resolve ``ghg_tool`` to the system-installed editable path rather than
    the local ``src/`` tree.  Clearing the cache forces a fresh file read
    from whatever path ``i18n.__file__`` resolves to, ensuring the tests
    see the current worktree's JSON files when ``sys.path`` is patched by
    pytest's ``pythonpath`` setting.
    """
    from ghg_tool.ui.streamlit_app.lib.i18n import _CACHE

    _CACHE.clear()

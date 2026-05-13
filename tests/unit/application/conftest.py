"""Re-export shared fixtures from ``tests.unit.calc.conftest``.

The orchestrator and intensity tests need the same in-memory factor
catalog and GWPSetTable fixtures used by the calc tests; pytest fixtures
are not auto-shared across sibling packages, so they're re-imported here.
"""

from __future__ import annotations

from tests.unit.calc.conftest import (  # noqa: F401
    InMemoryFactorCatalog,
    ar5_gwp,
    ar6_gwp,
    catalog,
    correlation_id,
    factor_seed,
)

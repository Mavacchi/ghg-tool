"""Root conftest for all unit tests.

Provides fixtures that must apply across ALL unit test files to prevent
state leakage between tests.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")


@pytest.fixture(autouse=True)
def _reset_rate_limit_counters() -> None:
    """Reset in-process rate-limit counters before each test.

    The rate-limit counters are module-level singletons that persist across
    tests in the same process.  Without a reset, a test that exhausts the
    counter (e.g. SEC-P1-003 tests) would cause all subsequent tests that
    share the same IP key (``ip:testclient``) to receive 429 instead of the
    expected response.

    This fixture runs before every unit test to ensure a clean counter state.
    """
    from ghg_tool.api.middleware.rate_limit import _counter, login_limiter

    _counter.reset()
    login_limiter.reset()

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
# SEC-P1-007: force the in-memory Redis fallback for all unit tests so the
# suite never reaches out to a live server.  Production behaviour is
# unchanged -- the fallback is only honoured when this env var is set.
os.environ.setdefault("GHG_REDIS_DISABLED", "1")


@pytest.fixture(autouse=True)
def _reset_redis_state() -> None:
    """Drop the Redis singleton + blacklist between every unit test.

    SEC-P1-007: the in-memory fallback is process-wide; without this
    reset a previous test's blacklisted jti would carry over and a
    later test that happens to mint a token with the same uuid would
    spuriously be rejected.  ``reset_for_testing`` flushes the shim and
    drops the cached client so the next ``get_redis_client()`` call
    re-evaluates env (still GHG_REDIS_DISABLED=1).
    """
    from ghg_tool.infrastructure import redis_client

    redis_client.reset_for_testing()


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

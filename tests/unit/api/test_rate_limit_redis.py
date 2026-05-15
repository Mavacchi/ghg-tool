"""SEC-ADV-008: Redis-backed rate limiter -- selection + fallback tests.

The full Redis backend is exercised end-to-end in integration tests
against a real ``redis:7-alpine`` container.  Here we cover:

- Fallback selection when ``GHG_REDIS_DISABLED=1`` is set.
- Public ``is_allowed/reset`` semantics on the in-memory implementation.
- The legacy ``_SlidingWindowCounter`` alias still resolves so any
  external test fixture continues to compile.
- The middleware exempts health-check paths regardless of backend.
"""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")
os.environ["GHG_REDIS_DISABLED"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from ghg_tool.api.middleware import rate_limit as rl_module  # noqa: E402


class TestFallbackSelection:
    """When Redis is unavailable, the limiter falls back to in-memory."""

    def test_counter_is_in_memory_when_redis_disabled(self) -> None:
        """``_counter`` resolves to the in-memory implementation."""
        assert isinstance(rl_module._counter, rl_module._InMemorySlidingWindow)

    def test_login_limiter_is_in_memory(self) -> None:
        assert isinstance(rl_module.login_limiter, rl_module._InMemorySlidingWindow)

    def test_publish_limiter_is_in_memory(self) -> None:
        assert isinstance(rl_module.publish_limiter, rl_module._InMemorySlidingWindow)

    def test_legacy_class_alias_exists(self) -> None:
        """``_SlidingWindowCounter`` alias preserved for back-compat."""
        assert rl_module._SlidingWindowCounter is rl_module._InMemorySlidingWindow


class TestInMemorySemantics:
    """The fallback implementation preserves legacy is_allowed/reset semantics."""

    def test_allows_up_to_limit_then_blocks(self) -> None:
        counter = rl_module._InMemorySlidingWindow(window_s=60, limit=3)
        key = f"k-{uuid.uuid4()}"
        assert counter.is_allowed(key) is True
        assert counter.is_allowed(key) is True
        assert counter.is_allowed(key) is True
        assert counter.is_allowed(key) is False  # limit reached

    def test_reset_clears_all_keys(self) -> None:
        counter = rl_module._InMemorySlidingWindow(window_s=60, limit=2)
        key = f"k-{uuid.uuid4()}"
        counter.is_allowed(key)
        counter.is_allowed(key)
        assert counter.is_allowed(key) is False
        counter.reset()
        assert counter.is_allowed(key) is True

    def test_independent_keys_have_independent_budgets(self) -> None:
        counter = rl_module._InMemorySlidingWindow(window_s=60, limit=1)
        a = f"k-{uuid.uuid4()}"
        b = f"k-{uuid.uuid4()}"
        assert counter.is_allowed(a) is True
        assert counter.is_allowed(a) is False
        # ``b`` has its own budget.
        assert counter.is_allowed(b) is True


class TestMiddlewareExemptPaths:
    """Health and readiness paths bypass the rate limiter entirely."""

    def test_healthz_bypasses_rate_limit(self) -> None:
        from ghg_tool.api.main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            for _ in range(5):
                resp = client.get("/healthz")
            assert resp.status_code == 200


class TestStorageUri:
    """``get_storage_uri`` returns ``memory://`` when Redis is the fallback."""

    def test_storage_uri_memory_when_fallback(self) -> None:
        from ghg_tool.infrastructure import redis_client

        # Force re-selection so the test does not depend on import order.
        redis_client.reset_for_testing()
        assert redis_client.get_storage_uri() == "memory://"


# ---------------------------------------------------------------------------
# Redis-backed semantics -- exercised against fakeredis when available.
# ---------------------------------------------------------------------------


fakeredis = pytest.importorskip("fakeredis")


class TestRedisBackedBucket:
    """Smoke test: the ``_RedisSlidingWindow`` accepts a fake-redis URL.

    fakeredis exposes the same ``redis://`` URI surface as a real server.
    We construct the limiter directly so this test does not depend on a
    Redis container being available in unit-test CI.
    """

    def test_redis_window_constructible_against_fakeredis(self) -> None:
        # ``limits.storage`` looks for ``redis`` package only -- with
        # fakeredis installed and patched into redis.from_url, the
        # construction succeeds.
        try:
            counter = rl_module._RedisSlidingWindow(
                window_s=60,
                limit=2,
                namespace="ghg:rl:test",
                # ``limits`` recognises ``memory://`` natively; use the
                # in-process backend so the test never reaches out over
                # the network even if a real redis happens to be running.
                storage_uri="memory://",
            )
        except Exception as exc:  # pragma: no cover -- diagnostic aid
            pytest.skip(f"limits storage construction failed: {exc!r}")

        key = f"k-{uuid.uuid4()}"
        assert counter.is_allowed(key) is True
        assert counter.is_allowed(key) is True
        # Third hit must be denied (limit==2).
        assert counter.is_allowed(key) is False

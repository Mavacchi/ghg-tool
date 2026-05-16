"""Unit tests for ``ghg_tool.infrastructure.security.token_blacklist`` and the
underlying ``redis_client`` singleton -- SEC-P1-007 + SEC-ADV-008.

All tests run against the in-memory fallback (``GHG_REDIS_DISABLED=1``)
so no live Redis is required.  Production behaviour is exercised by the
shared API surface: any code path that works against the in-memory shim
must work against a real Redis since both expose the same ``RedisLike``
protocol.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")
# Force the in-memory shim so the test suite never reaches out to Redis.
os.environ["GHG_REDIS_DISABLED"] = "1"

from ghg_tool.infrastructure import redis_client  # noqa: E402
from ghg_tool.infrastructure.security import token_blacklist  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_redis_singleton() -> None:
    """Drop the cached client/state between tests."""
    redis_client.reset_for_testing()


class TestRedisClientFallback:
    """Behaviour of the in-memory fallback client."""

    def test_get_redis_client_returns_in_memory_when_disabled(self) -> None:
        """With GHG_REDIS_DISABLED=1 the fallback is selected."""
        client = redis_client.get_redis_client()
        assert redis_client.using_in_memory_fallback() is True
        # The fallback implements the documented surface
        assert client.ping() is True

    def test_get_redis_client_is_singleton(self) -> None:
        """Two calls return the same object."""
        a = redis_client.get_redis_client()
        b = redis_client.get_redis_client()
        assert a is b

    def test_get_storage_uri_returns_memory_when_fallback(self) -> None:
        """slowapi storage URI is ``memory://`` for the fallback."""
        assert redis_client.get_storage_uri() == "memory://"

    def test_in_memory_setex_and_exists(self) -> None:
        """setex + exists roundtrip works on the shim."""
        client = redis_client.get_redis_client()
        client.setex("k", 10, "v")
        assert client.exists("k") == 1

    def test_in_memory_delete(self) -> None:
        """delete drops the key."""
        client = redis_client.get_redis_client()
        client.setex("k", 10, "v")
        assert client.delete("k") == 1
        assert client.exists("k") == 0

    def test_in_memory_setex_rejects_non_positive_ttl(self) -> None:
        """Mirrors redis-py: TTL must be > 0."""
        client = redis_client.get_redis_client()
        with pytest.raises(ValueError):
            client.setex("k", 0, "v")

    def test_in_memory_ttl_expiry(self) -> None:
        """Entries auto-expire after the configured TTL (1 s window).

        We patch the clock so the test runs in milliseconds rather than
        sleeping for a real second.
        """
        client = redis_client.get_redis_client()
        client.setex("ephemeral", 1, "v")
        assert client.exists("ephemeral") == 1

        # Advance the monotonic clock past the TTL via the module hook.
        original = redis_client._now_monotonic  # type: ignore[attr-defined]
        try:
            redis_client._now_monotonic = lambda: original() + 2.0  # type: ignore[attr-defined]
            assert client.exists("ephemeral") == 0
        finally:
            redis_client._now_monotonic = original  # type: ignore[attr-defined]


class TestTokenBlacklistRevoke:
    """Behaviour of the blacklist API itself (SEC-P1-007)."""

    def test_revoke_then_is_revoked(self) -> None:
        jti = str(uuid.uuid4())
        token_blacklist.revoke(jti, ttl_seconds=60)
        assert token_blacklist.is_revoked(jti) is True

    def test_is_revoked_unknown_jti_false(self) -> None:
        assert token_blacklist.is_revoked(str(uuid.uuid4())) is False

    def test_is_revoked_empty_string_false(self) -> None:
        """Empty jti must not match a stray empty key in Redis."""
        assert token_blacklist.is_revoked("") is False

    def test_revoke_empty_jti_raises(self) -> None:
        with pytest.raises(ValueError):
            token_blacklist.revoke("", ttl_seconds=60)

    def test_revoke_ttl_clamped_low(self) -> None:
        """A negative or zero TTL is clamped up to _MIN_TTL_S."""
        jti = str(uuid.uuid4())
        token_blacklist.revoke(jti, ttl_seconds=-100)
        # Still recorded -- exists returns 1.
        assert token_blacklist.is_revoked(jti) is True

    def test_revoke_ttl_clamped_high(self) -> None:
        """A ridiculous TTL is clamped down to _MAX_TTL_S."""
        jti = str(uuid.uuid4())
        # 10 years -- well above the cap.
        token_blacklist.revoke(jti, ttl_seconds=10 * 365 * 86400)
        assert token_blacklist.is_revoked(jti) is True

    def test_revoke_from_claims_uses_exp(self) -> None:
        """``exp`` claim drives the TTL via revoke_from_claims."""
        jti = str(uuid.uuid4())
        claims = {"jti": jti, "exp": int(time.time()) + 60}
        token_blacklist.revoke_from_claims(claims, reason="test")
        assert token_blacklist.is_revoked(jti) is True

    def test_revoke_from_claims_past_exp_still_recorded(self) -> None:
        """A token whose exp is in the past is still recorded (min TTL)."""
        jti = str(uuid.uuid4())
        claims = {"jti": jti, "exp": int(time.time()) - 3600}
        token_blacklist.revoke_from_claims(claims)
        assert token_blacklist.is_revoked(jti) is True

    def test_revoke_from_claims_missing_jti_is_silent(self) -> None:
        """Missing jti -> log + bail, never raise."""
        # No exception, no state change for unrelated keys.
        token_blacklist.revoke_from_claims({"exp": int(time.time()) + 60})
        # Sanity: an unrelated jti remains absent.
        assert token_blacklist.is_revoked(str(uuid.uuid4())) is False

    def test_clear_for_testing_drops_entry(self) -> None:
        jti = str(uuid.uuid4())
        token_blacklist.revoke(jti, ttl_seconds=60)
        assert token_blacklist.is_revoked(jti) is True
        token_blacklist.clear_for_testing(jti)
        assert token_blacklist.is_revoked(jti) is False


class TestTokenBlacklistFailClosed:
    """REQUIRED-2 — Redis outage must surface JWTUnavailableError, not False.

    The auth dependency maps this exception to HTTP 503; the unit test
    here pins the contract so a future refactor cannot silently turn
    ``is_revoked`` back into a fail-open swallow-and-return-False.
    """

    def test_is_revoked_raises_when_backend_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A ConnectionError from the backend must surface as JWTUnavailableError."""

        class _BrokenClient:
            def exists(self, _name: str) -> int:
                raise ConnectionError("simulated redis outage")

            def setex(self, *_a: object, **_k: object) -> bool:
                return True

            def delete(self, *_a: object) -> int:
                return 0

            def ping(self) -> bool:
                return False

        monkeypatch.setattr(
            token_blacklist, "get_redis_client", lambda: _BrokenClient()
        )

        with pytest.raises(token_blacklist.JWTUnavailableError):
            token_blacklist.is_revoked(str(uuid.uuid4()))

    def test_is_revoked_raises_when_backend_times_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A TimeoutError from the backend must also surface as JWTUnavailableError."""

        class _TimingOutClient:
            def exists(self, _name: str) -> int:
                raise TimeoutError("simulated redis timeout")

            def setex(self, *_a: object, **_k: object) -> bool:
                return True

            def delete(self, *_a: object) -> int:
                return 0

            def ping(self) -> bool:
                return False

        monkeypatch.setattr(
            token_blacklist, "get_redis_client", lambda: _TimingOutClient()
        )

        with pytest.raises(token_blacklist.JWTUnavailableError):
            token_blacklist.is_revoked(str(uuid.uuid4()))

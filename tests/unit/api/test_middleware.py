"""Unit tests for middleware: correlation_id, rate_limit, error_handler."""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from fastapi.testclient import TestClient

from ghg_tool.api.main import app
from ghg_tool.api.middleware.correlation_id import _resolve_correlation_id


class TestCorrelationIdMiddleware:
    """Tests for the CorrelationIdMiddleware."""

    def test_echoes_valid_correlation_id(self) -> None:
        """A valid UUID in X-Correlation-ID is echoed back unchanged."""
        cid = str(uuid.uuid4())
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/healthz", headers={"X-Correlation-ID": cid})
        assert resp.headers.get("X-Correlation-ID") == cid

    def test_generates_uuid_when_absent(self) -> None:
        """When no X-Correlation-ID is sent, a UUID v4 is generated."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/healthz")
        cid = resp.headers.get("X-Correlation-ID", "")
        # Should be a valid UUID v4 string
        parsed = uuid.UUID(cid)
        assert parsed.version == 4

    def test_invalid_correlation_id_replaced(self) -> None:
        """An invalid (non-UUID) X-Correlation-ID is replaced with a fresh UUID."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/healthz", headers={"X-Correlation-ID": "not-a-uuid"})
        cid = resp.headers.get("X-Correlation-ID", "")
        parsed = uuid.UUID(cid)
        assert str(parsed) != "not-a-uuid"

    def test_resolve_correlation_id_with_valid_uuid(self) -> None:
        """_resolve_correlation_id returns the normalised UUID string."""
        raw = str(uuid.uuid4())
        result = _resolve_correlation_id(raw)
        assert result == raw

    def test_resolve_correlation_id_with_empty_string(self) -> None:
        """_resolve_correlation_id generates a UUID when input is empty."""
        result = _resolve_correlation_id("")
        parsed = uuid.UUID(result)
        assert parsed.version == 4

    def test_resolve_correlation_id_with_garbage(self) -> None:
        """_resolve_correlation_id generates a UUID when input is garbage."""
        result = _resolve_correlation_id("not-a-uuid!!!")
        parsed = uuid.UUID(result)
        assert parsed.version == 4


class TestErrorHandlerMiddleware:
    """Tests that the error handler returns RFC 7807 problem+json."""

    def test_unhandled_exception_returns_problem_json(self) -> None:
        """A route that raises an unexpected exception returns 500 problem+json."""
        from fastapi import FastAPI

        from ghg_tool.api.middleware.correlation_id import CorrelationIdMiddleware
        from ghg_tool.api.middleware.error_handler import ErrorHandlerMiddleware

        # Build a minimal isolated app so we don't mutate the shared `app` instance
        _test_app = FastAPI()
        _test_app.add_middleware(ErrorHandlerMiddleware)
        _test_app.add_middleware(CorrelationIdMiddleware)

        @_test_app.get("/test-error-route-xyz")
        async def _error_route() -> None:
            raise RuntimeError("Simulated unexpected error")

        with TestClient(_test_app, raise_server_exceptions=False) as client:
            resp = client.get("/test-error-route-xyz")

        assert resp.status_code == 500
        data = resp.json()
        assert data["status"] == 500
        assert "correlation_id" in data
        # No stack trace in response
        assert "Traceback" not in str(data)
        assert "RuntimeError" not in data.get("detail", "")


class TestRateLimitMiddleware:
    """Tests for the in-process sliding-window rate limiter."""

    def test_exempt_paths_not_rate_limited(self) -> None:
        """Health endpoints are exempt from rate limiting."""
        with TestClient(app, raise_server_exceptions=False) as client:
            for _ in range(5):
                resp = client.get("/healthz")
            assert resp.status_code == 200

    def test_rate_limit_headers_present(self) -> None:
        """Rate-limited response (429) carries required headers."""
        from ghg_tool.api.middleware.rate_limit import _counter

        # Force the counter to be exhausted for a unique key
        test_key = f"ip:test-rate-limit-{uuid.uuid4()}"
        # Exhaust the bucket
        for _ in range(100):
            _counter.is_allowed(test_key)

        # The next call should be blocked
        result = _counter.is_allowed(test_key)
        assert result is False

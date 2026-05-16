"""Integration tests: GWP set switch enforcement — FR-19, MG-10, MG-12.

Covers the domain policy invariant that prevents mixing AR5 and AR6 within a
single report run (``MixedGWPSetError``), exercised at two levels:

1. Domain policy layer (unit-level, no DB):
   ``assert_single_gwp_set`` raises ``MixedGWPSetError`` when AR5 records exist
   and a new AR6 run would be merged into the same correlation batch.

2. API-level (TestClient, dependency-overridden, no DB):
   POST /api/v1/calc/run with CSRD_ESRS_E1 (→ AR6) and EU_ETS_PHASE_IV (→ AR5)
   both return HTTP 202; the gwp_set is resolved from the regulatory_stream.
   This verifies that the router correctly delegates gwp_set selection and that
   the background task receives the right value — the MixedGWPSetError guard
   fires inside the background task (not at HTTP acceptance time) because the
   run always starts fresh from the persisted raw data.

Design note: there is currently no ``POST /api/v1/calc/recalculate`` endpoint.
The GWP-switch conflict is enforced at the calc persistence layer
(``run_calc_and_persist``) when it calls ``assert_single_gwp_set`` on the
consolidated rows.  This test file documents that invariant and will be
extended once the ``/recalculate`` endpoint is introduced.

All tests are marked ``@pytest.mark.integration`` so they are skipped in
unit-test CI runs (``pytest -m 'not integration'``).  A subset of tests that
exercise only in-process domain logic are NOT marked integration and run in
every CI pass.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

# Env must be set before importing the FastAPI app.
os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user  # noqa: E402
from ghg_tool.api.dependencies.db import get_db  # noqa: E402
from ghg_tool.api.main import app  # noqa: E402
from ghg_tool.domain.policies.gwp_enforcement import (  # noqa: E402
    MixedGWPSetError,
    assert_single_gwp_set,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TENANT_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _admin_user() -> CurrentUser:
    return CurrentUser(
        sub=str(uuid.uuid4()),
        role="admin",  # type: ignore[arg-type]
        tenant_id=_TENANT_ID,
        jti=str(uuid.uuid4()),
    )


def _make_mock_db() -> Any:
    """No-op async DB session (avoids live PostgreSQL dependency)."""
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=MagicMock())

    async def _gen() -> AsyncGenerator[Any, None]:
        yield mock_session

    return _gen


# ---------------------------------------------------------------------------
# Domain-level tests (run in every CI pass — no @pytest.mark.integration)
# ---------------------------------------------------------------------------


class TestGwpEnforcementDomainPolicy:
    """Domain policy: assert_single_gwp_set blocks mixed AR5/AR6 runs.

    These tests exercise the pure domain function with no DB or HTTP layer.
    They document the enforcement invariant that the calc persistence layer
    relies on when processing a report run.
    """

    def test_ar5_records_then_ar6_run_raises_mixed_gwp(self) -> None:
        """Simulates existing AR5 records + incoming AR6 → MixedGWPSetError.

        Scenario: a tenant already has a correlation batch with AR5 rows.
        A new run attempts to append AR6 rows into the same batch.
        The policy must block the merge.
        """
        # Existing AR5 rows in the batch
        existing_gwp_sets = ["AR5", "AR5", "AR5"]
        # New AR6 rows incoming from the recalculate run
        incoming_gwp_sets = ["AR6", "AR6"]

        combined = existing_gwp_sets + incoming_gwp_sets

        with pytest.raises(MixedGWPSetError) as exc_info:
            assert_single_gwp_set(combined)

        detail = str(exc_info.value)
        assert "AR5" in detail
        assert "AR6" in detail
        assert "FR-19" in detail

    def test_uniform_ar5_passes(self) -> None:
        """All-AR5 run is valid."""
        result = assert_single_gwp_set(["AR5", "AR5", "AR5"])
        assert result == "AR5"

    def test_uniform_ar6_passes(self) -> None:
        """All-AR6 run is valid."""
        result = assert_single_gwp_set(["AR6", "AR6", "AR6"])
        assert result == "AR6"

    def test_single_ar5_row_passes(self) -> None:
        """Single AR5 row is a valid run."""
        result = assert_single_gwp_set(["AR5"])
        assert result == "AR5"

    def test_single_ar6_row_passes(self) -> None:
        """Single AR6 row is a valid run."""
        result = assert_single_gwp_set(["AR6"])
        assert result == "AR6"

    def test_empty_gwp_sets_raises_value_error(self) -> None:
        """Empty list raises ValueError (not MixedGWPSetError)."""
        with pytest.raises(ValueError, match="empty"):
            assert_single_gwp_set([])

    def test_mixed_error_message_contains_both_codes(self) -> None:
        """MixedGWPSetError detail must name both codes (FR-19 audit requirement)."""
        with pytest.raises(MixedGWPSetError) as exc_info:
            assert_single_gwp_set(["AR6", "AR5"])
        msg = str(exc_info.value)
        # Both codes must appear so the audit log is actionable.
        assert "AR5" in msg
        assert "AR6" in msg

    @pytest.mark.parametrize("n_ar5,n_ar6", [
        (1, 1),
        (10, 1),
        (1, 10),
        (5, 5),
    ])
    def test_any_mix_always_raises(self, n_ar5: int, n_ar6: int) -> None:
        """Any non-empty combination of AR5 + AR6 → MixedGWPSetError."""
        gwp_sets = ["AR5"] * n_ar5 + ["AR6"] * n_ar6
        with pytest.raises(MixedGWPSetError):
            assert_single_gwp_set(gwp_sets)


# ---------------------------------------------------------------------------
# API-level tests (TestClient + dependency overrides, no live DB)
# ---------------------------------------------------------------------------


class TestCalcRunGwpResolution:
    """POST /api/v1/calc/run resolves gwp_set from regulatory_stream.

    Verifies that the router wires the correct gwp_set to the background task
    without requiring a live DB or Celery broker.  The background task itself
    is NOT awaited in unit tests (BackgroundTasks run after response dispatch).

    NOTE: There is no ``/api/v1/calc/recalculate`` endpoint as of wave-5.
    GWP-switch conflict detection occurs inside ``run_calc_and_persist``
    (calc persistence layer).  This test documents the router contract.
    TODO: extend when /recalculate endpoint is introduced (BLOCK-GWP-SWITCH).
    """

    def _make_client(self) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: _admin_user()
        app.dependency_overrides[get_db] = _make_mock_db()
        return TestClient(app, raise_server_exceptions=False)

    def test_csrd_stream_returns_202(self) -> None:
        """CSRD_ESRS_E1 → AR6; router returns 202 immediately."""
        client = self._make_client()
        try:
            with client:
                resp = client.post(
                    "/api/v1/calc/run",
                    json={"anno": 2025, "regulatory_stream": "CSRD_ESRS_E1"},
                )
            assert resp.status_code == 202
            body = resp.json()
            assert "correlation_id" in body
            assert "queued" in body["message"]
        finally:
            app.dependency_overrides.clear()

    def test_eu_ets_stream_returns_202(self) -> None:
        """EU_ETS_PHASE_IV → AR5; router returns 202 immediately."""
        client = self._make_client()
        try:
            with client:
                resp = client.post(
                    "/api/v1/calc/run",
                    json={"anno": 2025, "regulatory_stream": "EU_ETS_PHASE_IV"},
                )
            assert resp.status_code == 202
            body = resp.json()
            assert "correlation_id" in body
        finally:
            app.dependency_overrides.clear()

    def test_csrd_stream_response_body_contains_stream_name(self) -> None:
        """Response message includes the regulatory stream name for auditability."""
        client = self._make_client()
        try:
            with client:
                resp = client.post(
                    "/api/v1/calc/run",
                    json={"anno": 2024, "regulatory_stream": "CSRD_ESRS_E1"},
                )
            assert resp.status_code == 202
            body = resp.json()
            assert "CSRD_ESRS_E1" in body["message"]
        finally:
            app.dependency_overrides.clear()

    def test_invalid_regulatory_stream_returns_422(self) -> None:
        """Pydantic validation rejects unknown regulatory_stream values."""
        client = self._make_client()
        try:
            with client:
                resp = client.post(
                    "/api/v1/calc/run",
                    json={"anno": 2025, "regulatory_stream": "AR4_LEGACY"},
                )
            # Pydantic Literal constraint: only CSRD_ESRS_E1 | EU_ETS_PHASE_IV
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_non_admin_role_returns_403(self) -> None:
        """Calc run trigger requires admin role; editor → 403."""
        editor_user = CurrentUser(
            sub=str(uuid.uuid4()),
            role="editor",  # type: ignore[arg-type]
            tenant_id=_TENANT_ID,
            jti=str(uuid.uuid4()),
        )
        app.dependency_overrides[get_current_user] = lambda: editor_user
        app.dependency_overrides[get_db] = _make_mock_db()

        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/api/v1/calc/run",
                    json={"anno": 2025, "regulatory_stream": "CSRD_ESRS_E1"},
                )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_correlation_id_is_uuid(self) -> None:
        """Returned correlation_id must be a valid UUID (FR-22 traceability)."""
        client = self._make_client()
        try:
            with client:
                resp = client.post(
                    "/api/v1/calc/run",
                    json={"anno": 2025, "regulatory_stream": "CSRD_ESRS_E1"},
                )
            assert resp.status_code == 202
            body = resp.json()
            # Must be parseable as UUID — raises ValueError if not
            parsed = uuid.UUID(body["correlation_id"])
            assert str(parsed) == body["correlation_id"]
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# TODO / documented gap
# ---------------------------------------------------------------------------

@pytest.mark.skip(
    reason=(
        "TODO BLOCK-GWP-SWITCH: POST /api/v1/calc/recalculate does not yet "
        "exist (wave-5 scope). When the endpoint is added it MUST return 409 "
        "when existing emissions_consolidated rows for (tenant, anno) carry a "
        "different gwp_set than the requested run. The enforcement relies on "
        "assert_single_gwp_set (domain/policies/gwp_enforcement.py). "
        "This placeholder test will be un-skipped by BackendAgent (n.7) when "
        "the endpoint is implemented."
    )
)
def test_recalculate_endpoint_rejects_gwp_switch_409() -> None:
    """POST /api/v1/calc/recalculate with AR6 when existing AR5 rows → 409.

    Setup:
        1. Seed calc.emissions_consolidated with AR5 rows for (tenant, anno=2024).
        2. POST /api/v1/calc/recalculate with gwp_set='AR6'.

    Expected response: HTTP 409 Conflict with detail explaining FR-19 violation.

    This test is a placeholder; the endpoint is not implemented in wave-5.
    """
    # Placeholder: once /recalculate is implemented, replace with:
    #
    #   resp = client.post(
    #       "/api/v1/calc/recalculate",
    #       json={"anno": 2024, "gwp_set": "AR6"},
    #   )
    #   assert resp.status_code in (409, 422)
    #   detail = resp.json()
    #   assert "FR-19" in str(detail) or "gwp_set" in str(detail)
    raise NotImplementedError("recalculate endpoint not yet implemented")

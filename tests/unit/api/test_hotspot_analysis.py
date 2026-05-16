"""Unit + integration-stub tests for the Scope 3 hot-spot analysis service
and endpoint (Wave4 Task C).

Tests are organised in two sections:
  Section 1 — Service unit tests (pure Python, no DB):
    Direct calls to ``compute_hotspots`` with mock async sessions.
  Section 2 — Router integration-stub tests (FastAPI TestClient):
    HTTP-level tests with mocked DB and auth.

Count: 8 tests (meets the ≥ 8 requirement).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# Environment must be set before importing the app
os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.main import app
from ghg_tool.application.services.hotspot_analysis_service import (
    HotspotReport,
    NoDataForAnnoError,
    _priority,
    compute_hotspots,
)

TEST_TENANT_ID = str(uuid.uuid4())
TEST_USER_ID = str(uuid.uuid4())

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str = "viewer") -> CurrentUser:
    return CurrentUser(
        sub=TEST_USER_ID,
        role=role,  # type: ignore[arg-type]
        tenant_id=TEST_TENANT_ID,
        jti=str(uuid.uuid4()),
    )


def _build_mock_session(
    *,
    total_rows: int = 5,
    s3_rows: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Build a mock async session for hotspot tests.

    Args:
        total_rows: Number of rows returned by the anno existence check.
            Set to 0 to trigger ``NoDataForAnnoError``.
        s3_rows: Rows to return from the per-category S3 query.
            Each dict must have ``sub_scope``, ``tco2e``, and ``pct`` keys.
            When None, returns an empty list.

    Returns:
        MagicMock with a tracked async ``execute`` method.
    """
    if s3_rows is None:
        s3_rows = []

    call_index = [0]

    def _anno_check_result() -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = total_rows
        return result

    def _s3_result() -> MagicMock:
        result = MagicMock()
        mock_mappings = MagicMock()
        mock_mappings.all.return_value = s3_rows
        result.mappings.return_value = mock_mappings
        return result

    async def _execute(stmt: Any, params: Any = None) -> MagicMock:
        idx = call_index[0]
        call_index[0] += 1
        if idx == 0:
            return _anno_check_result()
        return _s3_result()

    session = MagicMock()
    session.execute = _execute
    return session


# ---------------------------------------------------------------------------
# Section 1 — Service unit tests
# ---------------------------------------------------------------------------


def test_priority_thresholds_correct() -> None:
    """Priority helper assigns tiers correctly per GHG Protocol Scope 3 §10."""
    assert _priority(Decimal("25")) == "HIGH"
    assert _priority(Decimal("20.01")) == "HIGH"
    assert _priority(Decimal("20")) == "MEDIUM"
    assert _priority(Decimal("5")) == "MEDIUM"
    assert _priority(Decimal("4.99")) == "LOW"
    assert _priority(Decimal("0")) == "LOW"


def test_compute_hotspots_no_anno_data_raises_404_error() -> None:
    """NoDataForAnnoError raised when anno has zero rows for the tenant."""
    session = _build_mock_session(total_rows=0)
    with pytest.raises(NoDataForAnnoError):
        asyncio.run(
            compute_hotspots(session, tenant_id=TEST_TENANT_ID, anno=2024)
        )


def test_compute_hotspots_no_s3_data_returns_empty_report() -> None:
    """When anno has rows but no Scope 3 data, report has total=0 and empty list."""
    # total_rows=3 means the anno exists (other scopes), but s3_rows=[] (no S3)
    session = _build_mock_session(total_rows=3, s3_rows=[])
    report = asyncio.run(
        compute_hotspots(session, tenant_id=TEST_TENANT_ID, anno=2024)
    )
    assert isinstance(report, HotspotReport)
    assert report.total_s3_tco2e == Decimal("0")
    assert report.hotspots == []
    assert "Scope 3" in report.methodology_note


def test_compute_hotspots_returns_correct_ranking() -> None:
    """Categories are returned in the order the DB supplies (SQL handles ORDER BY).

    The service preserves DB row order — the SQL CTE sorts by tco2e DESC.
    In the unit test the mock returns rows in the exact order supplied, so we
    pass them pre-sorted (descending by tco2e) to mirror what the DB would do.
    Priority tiers are verified per-row.
    """
    # Pre-sorted descending as the SQL ORDER BY tco2e DESC would return
    s3_rows = [
        {"sub_scope": "Cat1", "tco2e": Decimal("500"), "pct": Decimal("50")},
        {"sub_scope": "Cat4", "tco2e": Decimal("300"), "pct": Decimal("30")},
        {"sub_scope": "Cat6", "tco2e": Decimal("200"), "pct": Decimal("20")},
    ]
    session = _build_mock_session(total_rows=10, s3_rows=s3_rows)
    report = asyncio.run(
        compute_hotspots(session, tenant_id=TEST_TENANT_ID, anno=2024, top_n=5)
    )
    assert len(report.hotspots) == 3
    # First hotspot: Cat1 at 50% → HIGH
    assert report.hotspots[0].sub_scope == "Cat1"
    assert report.hotspots[0].tco2e == Decimal("500")
    assert report.hotspots[0].priority == "HIGH"   # 50% > 20%
    # Second: Cat4 at 30% → HIGH
    assert report.hotspots[1].sub_scope == "Cat4"
    assert report.hotspots[1].priority == "HIGH"   # 30% > 20%
    # Third: Cat6 at 20% → MEDIUM (boundary: 20% is not > 20%)
    assert report.hotspots[2].sub_scope == "Cat6"
    assert report.hotspots[2].priority == "MEDIUM"  # 20% not > 20%, >= 5%


def test_compute_hotspots_total_tco2e_is_sum_of_categories() -> None:
    """total_s3_tco2e is the sum of all returned category tco2e values."""
    s3_rows = [
        {"sub_scope": "Cat1", "tco2e": Decimal("100.5"), "pct": Decimal("60")},
        {"sub_scope": "Cat3", "tco2e": Decimal("66.75"), "pct": Decimal("40")},
    ]
    session = _build_mock_session(total_rows=5, s3_rows=s3_rows)
    report = asyncio.run(
        compute_hotspots(session, tenant_id=TEST_TENANT_ID, anno=2024)
    )
    expected_total = Decimal("100.5") + Decimal("66.75")
    assert report.total_s3_tco2e == expected_total


def test_compute_hotspots_methodology_note_cites_ghg_protocol() -> None:
    """Methodology note must cite GHG Protocol Scope 3 Standard §10."""
    s3_rows = [
        {"sub_scope": "Cat1", "tco2e": Decimal("100"), "pct": Decimal("100")},
    ]
    session = _build_mock_session(total_rows=3, s3_rows=s3_rows)
    report = asyncio.run(
        compute_hotspots(session, tenant_id=TEST_TENANT_ID, anno=2024)
    )
    assert "§10" in report.methodology_note or "10" in report.methodology_note
    assert "GHG Protocol" in report.methodology_note


# ---------------------------------------------------------------------------
# Section 2 — Router integration-stub tests
# ---------------------------------------------------------------------------

from collections.abc import AsyncGenerator  # noqa: E402


def _mock_db_session(s3_rows: list[dict[str, Any]], total_rows: int = 5) -> Any:
    """FastAPI dependency override returning a mock session.

    Args:
        s3_rows: Per-category rows to return from the hotspot SQL query.
        total_rows: Row count for the anno existence check.

    Returns:
        An async generator compatible with ``get_db``.
    """
    mock_session = _build_mock_session(total_rows=total_rows, s3_rows=s3_rows)

    async def _override() -> AsyncGenerator[Any, None]:
        yield mock_session

    return _override


def test_hotspot_endpoint_returns_200_with_data() -> None:
    """GET /api/v1/analysis/hotspots returns 200 with correct JSON structure."""
    s3_rows = [
        {"sub_scope": "Cat1", "tco2e": Decimal("1000"), "pct": Decimal("60")},
        {"sub_scope": "Cat6", "tco2e": Decimal("666"), "pct": Decimal("40")},
    ]
    app.dependency_overrides[get_current_user] = lambda: _make_user("viewer")
    app.dependency_overrides[get_db] = _mock_db_session(s3_rows, total_rows=5)

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/analysis/hotspots?anno=2024&top_n=5")

    app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "hotspots" in data
    assert "total_s3_tco2e" in data
    assert "methodology_note" in data
    assert len(data["hotspots"]) == 2
    # First entry is Cat1 (highest)
    assert data["hotspots"][0]["sub_scope"] == "Cat1"
    assert data["hotspots"][0]["priority"] == "HIGH"
    assert Decimal(data["total_s3_tco2e"]) == Decimal("1666")


def test_hotspot_endpoint_returns_404_when_no_anno_data() -> None:
    """GET /api/v1/analysis/hotspots returns 404 when anno has no rows."""
    app.dependency_overrides[get_current_user] = lambda: _make_user("viewer")
    app.dependency_overrides[get_db] = _mock_db_session([], total_rows=0)

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/analysis/hotspots?anno=2020")

    app.dependency_overrides.clear()

    assert resp.status_code == 404, resp.text
    detail = resp.json().get("detail", {})
    assert "2020" in str(detail) or "not found" in str(detail).lower()


def test_hotspot_endpoint_returns_200_empty_list_when_no_s3() -> None:
    """GET /api/v1/analysis/hotspots returns 200 with empty hotspots when S3 total = 0."""
    # Anno exists (total_rows=3) but no S3 data (s3_rows=[])
    app.dependency_overrides[get_current_user] = lambda: _make_user("viewer")
    app.dependency_overrides[get_db] = _mock_db_session([], total_rows=3)

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/analysis/hotspots?anno=2024")

    app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["hotspots"] == []
    assert Decimal(data["total_s3_tco2e"]) == Decimal("0")

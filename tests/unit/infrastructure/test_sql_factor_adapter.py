"""Unit tests for SqlFactorCatalogAdapter.

All tests mock the SQLAlchemy sync Engine so no live DB is required.

Coverage:
- happy path: factor found returns FactorRecord with expected fields
- not found: raises MissingFactorError
- draft factor (is_published=False): raises MissingFactorError (not visible)
- caches across calls: underlying SQL execute is called only once per key
"""

from __future__ import annotations

import contextlib
import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from ghg_tool.domain.exceptions.calc_errors import MissingFactorError
from ghg_tool.domain.ports.factor_catalog import FactorRecord
from ghg_tool.infrastructure.factors.sql_adapter import SqlFactorCatalogAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _make_engine(row: dict | None) -> MagicMock:
    """Return a mock Engine whose connect().execute() returns a single row.

    If row is None the mapping cursor returns no rows (factor not found).

    Args:
        row: Dict representing a DB row, or None for not-found.

    Returns:
        Mocked Engine.
    """
    engine = MagicMock()
    conn_ctx = MagicMock()

    result = MagicMock()
    mappings = MagicMock()
    if row is not None:
        # first() returns the row as a MagicMock with dict-like access
        fake_row = MagicMock()
        fake_row.__getitem__ = lambda self, k: row[k]
        mappings.first.return_value = fake_row
    else:
        mappings.first.return_value = None

    result.mappings.return_value = mappings
    conn_ctx.execute.return_value = result

    # Support `with engine.connect() as conn`
    conn_cm = MagicMock()
    conn_cm.__enter__ = MagicMock(return_value=conn_ctx)
    conn_cm.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value = conn_cm

    return engine


def _sample_row(
    factor_id: str = "LB_IT_GRID_ISPRA_2024",
    gwp_set: str = "AR6",
    is_tbc: bool = False,
    is_licence_only: bool = False,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "factor_id": factor_id,
        "version": "2025",
        "value": "0.27",
        "unit": "kg CO2 / kWh",
        "source": "ISPRA",
        "gwp_set": gwp_set,
        "biogenic_co2_kg_per_unit": None,
        "vintage": "2025",
        "applicability_note": None,
        "is_tbc": is_tbc,
        "is_licence_only": is_licence_only,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Factor found returns FactorRecord with expected fields."""

    def test_get_returns_factor_record(self) -> None:
        row = _sample_row()
        engine = _make_engine(row)
        adapter = SqlFactorCatalogAdapter(_TENANT_ID, sync_engine=engine)

        result = adapter.get("LB_IT_GRID_ISPRA_2024", gwp_set="AR6")

        assert isinstance(result, FactorRecord)
        assert result.factor_id == "LB_IT_GRID_ISPRA_2024"
        assert result.version == "2025"
        assert result.value == Decimal("0.27")
        assert result.unit == "kg CO2 / kWh"
        assert result.source == "ISPRA"
        assert result.gwp_set == "AR6"
        assert result.biogenic_co2_kg_per_unit is None
        assert result.is_tbc is False
        assert result.is_licence_only is False

    def test_get_biogenic_share_returns_value(self) -> None:
        row = _sample_row()
        row["biogenic_co2_kg_per_unit"] = "0.8"
        engine = _make_engine(row)
        adapter = SqlFactorCatalogAdapter(_TENANT_ID, sync_engine=engine)

        share = adapter.get_biogenic_share("LB_IT_GRID_ISPRA_2024", gwp_set="AR6")

        assert share == Decimal("0.8")

    def test_get_biogenic_share_none_when_not_set(self) -> None:
        engine = _make_engine(_sample_row())
        adapter = SqlFactorCatalogAdapter(_TENANT_ID, sync_engine=engine)

        share = adapter.get_biogenic_share("LB_IT_GRID_ISPRA_2024", gwp_set="AR6")

        assert share is None


class TestNotFound:
    """Missing factor raises MissingFactorError."""

    def test_get_raises_missing_factor_error(self) -> None:
        engine = _make_engine(None)
        adapter = SqlFactorCatalogAdapter(_TENANT_ID, sync_engine=engine)

        with pytest.raises(MissingFactorError, match="LB_IT_GRID_ISPRA_2024"):
            adapter.get("LB_IT_GRID_ISPRA_2024", gwp_set="AR6")

    def test_get_biogenic_share_returns_none_when_factor_missing(self) -> None:
        engine = _make_engine(None)
        adapter = SqlFactorCatalogAdapter(_TENANT_ID, sync_engine=engine)

        # Should not raise; returns None gracefully.
        result = adapter.get_biogenic_share("NONEXISTENT", gwp_set="AR6")
        assert result is None


class TestDraftNotVisible:
    """Draft factors (is_published=False) must not be returned.

    The SQL WHERE clause filters is_published=TRUE. We simulate this by
    making the engine return None (as the DB would for a draft-only factor).
    """

    def test_draft_factor_raises_missing_factor_error(self) -> None:
        # Engine returns None because the WHERE is_published=TRUE filters out drafts.
        engine = _make_engine(None)
        adapter = SqlFactorCatalogAdapter(_TENANT_ID, sync_engine=engine)

        with pytest.raises(MissingFactorError):
            adapter.get("DRAFT_FACTOR_001", gwp_set="AR6")

    def test_draft_factor_message_contains_factor_id(self) -> None:
        engine = _make_engine(None)
        adapter = SqlFactorCatalogAdapter(_TENANT_ID, sync_engine=engine)

        with pytest.raises(MissingFactorError, match="DRAFT_FACTOR_001"):
            adapter.get("DRAFT_FACTOR_001", gwp_set="AR6")


class TestCaching:
    """Cache: underlying SQL execute is called only once per (factor_id, gwp_set)."""

    def test_second_get_does_not_re_execute_sql(self) -> None:
        engine = _make_engine(_sample_row())
        adapter = SqlFactorCatalogAdapter(_TENANT_ID, sync_engine=engine)

        result1 = adapter.get("LB_IT_GRID_ISPRA_2024", gwp_set="AR6")
        result2 = adapter.get("LB_IT_GRID_ISPRA_2024", gwp_set="AR6")

        # connect() should have been called exactly once (one DB round-trip).
        assert engine.connect.call_count == 1
        assert result1 is result2

    def test_different_gwp_set_fetches_again(self) -> None:
        ar6_row = _sample_row(gwp_set="AR6")
        ar5_row = _sample_row(gwp_set="AR5")

        call_count = 0

        engine = MagicMock()

        def _connect():
            nonlocal call_count
            conn_ctx = MagicMock()
            result = MagicMock()
            mappings = MagicMock()
            row = ar6_row if call_count == 0 else ar5_row
            call_count += 1
            fake_row = MagicMock()
            fake_row.__getitem__ = lambda self, k: row[k]
            mappings.first.return_value = fake_row
            result.mappings.return_value = mappings
            conn_ctx.execute.return_value = result
            conn_cm = MagicMock()
            conn_cm.__enter__ = MagicMock(return_value=conn_ctx)
            conn_cm.__exit__ = MagicMock(return_value=False)
            return conn_cm

        engine.connect.side_effect = _connect

        adapter = SqlFactorCatalogAdapter(_TENANT_ID, sync_engine=engine)

        r_ar6 = adapter.get("LB_IT_GRID_ISPRA_2024", gwp_set="AR6")
        r_ar5 = adapter.get("LB_IT_GRID_ISPRA_2024", gwp_set="AR5")

        assert engine.connect.call_count == 2
        assert r_ar6.gwp_set == "AR6"
        assert r_ar5.gwp_set == "AR5"

    def test_vintage_year_is_separate_cache_key(self) -> None:
        engine = _make_engine(_sample_row())
        adapter = SqlFactorCatalogAdapter(_TENANT_ID, sync_engine=engine)

        # First call -- no vintage
        adapter.get("LB_IT_GRID_ISPRA_2024", gwp_set="AR6")
        # Second call -- same factor but with vintage_year -> different cache key
        with contextlib.suppress(MissingFactorError):
            adapter.get("LB_IT_GRID_ISPRA_2024", gwp_set="AR6", vintage_year=2025)

        # Two separate DB queries (two distinct cache keys).
        assert engine.connect.call_count == 2

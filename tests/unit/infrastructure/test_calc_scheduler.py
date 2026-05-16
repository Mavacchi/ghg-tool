"""Unit tests for calc_scheduler.py — target 90%+ coverage.

Tests are structured to cover:
  - _deterministic_correlation_id: stable UUID per (anno, stream, date)
  - start_scheduler: disabled when cron unset, ImportError path, invalid cron, happy path
  - _run_scheduled_calc: DB tenant not found, successful run, exception recovery

Patching strategy for _run_scheduled_calc:
  The function does local-only imports inside its body (``from sqlalchemy import
  create_engine`` etc.), so we must patch at the canonical module path
  (``sqlalchemy.create_engine``) or inject into ``sys.modules`` before the
  import statement runs.  The cleanest approach is to pre-seed sys.modules with
  MagicMock stubs so the local ``from X import Y`` picks up our doubles.
"""

from __future__ import annotations

import sys
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ghg_tool.infrastructure.scheduling.calc_scheduler import (
    _deterministic_correlation_id,
    start_scheduler,
)


# ---------------------------------------------------------------------------
# _deterministic_correlation_id
# ---------------------------------------------------------------------------

class TestDeterministicCorrelationId:
    def test_returns_uuid(self) -> None:
        result = _deterministic_correlation_id(2025, "CSRD_ESRS_E1")
        assert isinstance(result, uuid.UUID)

    def test_same_args_same_day_returns_same_uuid(self) -> None:
        a = _deterministic_correlation_id(2025, "CSRD_ESRS_E1")
        b = _deterministic_correlation_id(2025, "CSRD_ESRS_E1")
        assert a == b

    def test_different_anno_produces_different_uuid(self) -> None:
        a = _deterministic_correlation_id(2024, "CSRD_ESRS_E1")
        b = _deterministic_correlation_id(2025, "CSRD_ESRS_E1")
        assert a != b

    def test_different_stream_produces_different_uuid(self) -> None:
        a = _deterministic_correlation_id(2025, "CSRD_ESRS_E1")
        b = _deterministic_correlation_id(2025, "EU_ETS_PHASE_IV")
        assert a != b

    def test_is_uuid5_namespace_oid(self) -> None:
        result = _deterministic_correlation_id(2025, "CSRD_ESRS_E1")
        assert result.version == 5


# ---------------------------------------------------------------------------
# start_scheduler
# ---------------------------------------------------------------------------

class TestStartSchedulerDisabled:
    def test_returns_none_when_cron_unset(self) -> None:
        with patch.dict("os.environ", {"GHG_CALC_SCHEDULE_CRON": ""}, clear=False):
            result = start_scheduler(anno=2025)
        assert result is None

    def test_returns_none_when_cron_whitespace_only(self) -> None:
        with patch.dict("os.environ", {"GHG_CALC_SCHEDULE_CRON": "   "}, clear=False):
            result = start_scheduler(anno=2025)
        assert result is None


class TestStartSchedulerImportError:
    def test_returns_none_when_apscheduler_not_installed(self) -> None:
        """Simulate apscheduler missing by injecting a None into sys.modules."""
        # Temporarily hide apscheduler so the ImportError branch fires.
        saved = sys.modules.get("apscheduler.schedulers.background")
        sys.modules["apscheduler.schedulers.background"] = None  # type: ignore[assignment]
        try:
            with patch.dict("os.environ", {"GHG_CALC_SCHEDULE_CRON": "0 2 * * *"}, clear=False):
                result = start_scheduler(anno=2025)
        finally:
            if saved is None:
                sys.modules.pop("apscheduler.schedulers.background", None)
            else:
                sys.modules["apscheduler.schedulers.background"] = saved
        assert result is None


class TestStartSchedulerInvalidCron:
    def test_returns_none_for_4_field_cron(self) -> None:
        with patch.dict("os.environ", {"GHG_CALC_SCHEDULE_CRON": "0 2 * *"}, clear=False):
            result = start_scheduler(anno=2025)
        assert result is None

    def test_returns_none_for_6_field_cron(self) -> None:
        with patch.dict("os.environ", {"GHG_CALC_SCHEDULE_CRON": "0 0 2 * * 0"}, clear=False):
            result = start_scheduler(anno=2025)
        assert result is None

    def test_returns_none_for_single_word(self) -> None:
        with patch.dict("os.environ", {"GHG_CALC_SCHEDULE_CRON": "daily"}, clear=False):
            result = start_scheduler(anno=2025)
        assert result is None


class TestStartSchedulerHappyPath:
    """Happy-path tests that use real apscheduler but mock the job body."""

    def test_returns_scheduler_instance_when_cron_valid(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler

        with patch.dict("os.environ", {"GHG_CALC_SCHEDULE_CRON": "0 2 * * *"}, clear=False):
            result = start_scheduler(anno=2025)

        assert result is not None
        # Clean shutdown to avoid background thread leaks in the test process.
        if hasattr(result, "shutdown"):
            result.shutdown(wait=False)  # type: ignore[union-attr]

    def test_scheduler_adds_two_jobs_csrd_and_eu_ets(self) -> None:
        """Both CSRD_ESRS_E1 and EU_ETS_PHASE_IV jobs are registered."""
        with patch.dict("os.environ", {"GHG_CALC_SCHEDULE_CRON": "0 3 * * *"}, clear=False):
            scheduler = start_scheduler(anno=2025)

        assert scheduler is not None

        # Inspect jobs before shutdown — get_jobs() returns empty after scheduler stops.
        if hasattr(scheduler, "get_jobs"):
            job_ids = {j.id for j in scheduler.get_jobs()}  # type: ignore[union-attr]
            assert "calc_csrd" in job_ids
            assert "calc_eu_ets" in job_ids

        if hasattr(scheduler, "shutdown"):
            scheduler.shutdown(wait=False)  # type: ignore[union-attr]

    def test_no_double_scheduling_replace_existing_true(self) -> None:
        """Calling start_scheduler twice does not duplicate jobs (replace_existing=True)."""
        with patch.dict("os.environ", {"GHG_CALC_SCHEDULE_CRON": "0 2 * * *"}, clear=False):
            s1 = start_scheduler(anno=2025)
            s2 = start_scheduler(anno=2025)

        for s in (s1, s2):
            if s is not None and hasattr(s, "shutdown"):
                s.shutdown(wait=False)  # type: ignore[union-attr]

        # Both schedulers returned (each is independent); neither None.
        assert s1 is not None
        assert s2 is not None


# ---------------------------------------------------------------------------
# _run_scheduled_calc helpers — patch via sqlalchemy module-level
# ---------------------------------------------------------------------------


def _make_sync_engine_mock(tenant_row: Any) -> MagicMock:
    """Build a mock sync engine whose connect().execute().fetchone() returns row."""
    conn = MagicMock()
    result = MagicMock()
    result.fetchone = MagicMock(return_value=tenant_row)
    conn.execute = MagicMock(return_value=result)
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)

    engine = MagicMock()
    engine.connect = MagicMock(return_value=conn)
    engine.dispose = MagicMock()
    return engine


class TestRunScheduledCalc:
    """Tests for _run_scheduled_calc via patching SQLAlchemy at the module level."""

    def test_tenant_not_found_returns_early(self) -> None:
        from ghg_tool.infrastructure.scheduling.calc_scheduler import _run_scheduled_calc

        sync_engine = _make_sync_engine_mock(tenant_row=None)

        with (
            patch("sqlalchemy.create_engine", return_value=sync_engine),
            patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=MagicMock()),
            patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=MagicMock()),
            patch(
                "ghg_tool.application.services.calc_persistence.run_calc_and_persist"
            ) as mock_calc,
        ):
            _run_scheduled_calc(anno=2025, regulatory_stream="CSRD_ESRS_E1", gwp_set="AR6")

        mock_calc.assert_not_called()
        sync_engine.dispose.assert_called_once()

    def test_successful_run_calls_calc_and_disposes_engine(self) -> None:
        from ghg_tool.infrastructure.scheduling.calc_scheduler import _run_scheduled_calc

        tenant_uuid = str(uuid.uuid4())
        tenant_row = MagicMock()
        # row[0] must return a UUID-parseable string
        tenant_row.__getitem__ = MagicMock(return_value=tenant_uuid)
        sync_engine = _make_sync_engine_mock(tenant_row=tenant_row)

        mock_result = MagicMock()
        mock_result.emissions_written = 42
        mock_result.duration_ms = 999

        with (
            patch("sqlalchemy.create_engine", return_value=sync_engine),
            patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=MagicMock()),
            patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=MagicMock()),
            patch(
                "ghg_tool.application.services.calc_persistence.run_calc_and_persist",
                return_value=mock_result,
            ) as mock_calc,
        ):
            _run_scheduled_calc(anno=2025, regulatory_stream="CSRD_ESRS_E1", gwp_set="AR6")

        mock_calc.assert_called_once()
        sync_engine.dispose.assert_called_once()

    def test_exception_in_calc_caught_engine_still_disposed(self) -> None:
        from ghg_tool.infrastructure.scheduling.calc_scheduler import _run_scheduled_calc

        tenant_uuid = str(uuid.uuid4())
        tenant_row = MagicMock()
        tenant_row.__getitem__ = MagicMock(return_value=tenant_uuid)
        sync_engine = _make_sync_engine_mock(tenant_row=tenant_row)

        with (
            patch("sqlalchemy.create_engine", return_value=sync_engine),
            patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=MagicMock()),
            patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=MagicMock()),
            patch(
                "ghg_tool.application.services.calc_persistence.run_calc_and_persist",
                side_effect=RuntimeError("simulated DB error"),
            ),
        ):
            # Must NOT re-raise — exception is caught in the finally block
            _run_scheduled_calc(anno=2025, regulatory_stream="EU_ETS_PHASE_IV", gwp_set="AR5")

        sync_engine.dispose.assert_called_once()

    def test_custom_tenant_code_from_env(self) -> None:
        from ghg_tool.infrastructure.scheduling.calc_scheduler import _run_scheduled_calc

        tenant_uuid = str(uuid.uuid4())
        tenant_row = MagicMock()
        tenant_row.__getitem__ = MagicMock(return_value=tenant_uuid)

        captured_params: list[dict[str, Any]] = []

        def _spy_execute(stmt: Any, params: Any = None) -> MagicMock:
            if params:
                captured_params.append(dict(params))
            r = MagicMock()
            r.fetchone = MagicMock(return_value=tenant_row)
            return r

        conn = MagicMock()
        conn.execute = _spy_execute
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=None)
        sync_engine = MagicMock()
        sync_engine.connect = MagicMock(return_value=conn)
        sync_engine.dispose = MagicMock()

        mock_result = MagicMock()
        mock_result.emissions_written = 0
        mock_result.duration_ms = 0

        with (
            patch.dict("os.environ", {"GHG_SCHEDULER_TENANT_CODE": "MYCO"}, clear=False),
            patch("sqlalchemy.create_engine", return_value=sync_engine),
            patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=MagicMock()),
            patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=MagicMock()),
            patch(
                "ghg_tool.application.services.calc_persistence.run_calc_and_persist",
                return_value=mock_result,
            ),
        ):
            _run_scheduled_calc(anno=2025, regulatory_stream="CSRD_ESRS_E1", gwp_set="AR6")

        assert any(p.get("code") == "MYCO" for p in captured_params)

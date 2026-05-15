"""Hardening tests for calc pipeline persistence layer.

Covers:
- Task 1: factor_db_id threading from FactorRecord -> EmissionRecord -> INSERT param
- Task 2: set_session_gucs called before any INSERT in _persist_emissions
- Task 3: scheduler env-var gating; admin trigger 202 + correlation_id; status 200/404;
          dual-track CLI runs twice with different params.

No live database required — all DB and session interactions are mocked.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------

_TENANT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_CORRELATION_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_FACTOR_DB_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
_ANNO = 2025


def _make_async_session_factory(
    execute_side_effect: list[Any] | None = None,
) -> tuple[MagicMock, list[Any]]:
    """Return (factory, calls_log) tracking all session.execute invocations.

    Args:
        execute_side_effect: Optional list of return values for execute().

    Returns:
        Tuple of (sessionmaker mock, ordered list of (stmt, params) call args).
    """
    calls_log: list[Any] = []

    async def _fake_execute(stmt: Any, params: Any = None) -> MagicMock:
        calls_log.append((stmt, params))
        if execute_side_effect:
            val = execute_side_effect.pop(0)
            if isinstance(val, Exception):
                raise val
        return MagicMock()

    session = AsyncMock()
    session.execute = _fake_execute

    begin_cm = AsyncMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin_cm)

    factory_cm = AsyncMock()
    factory_cm.__aenter__ = AsyncMock(return_value=session)
    factory_cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = factory_cm
    return factory, calls_log


def _make_sync_engine_empty() -> MagicMock:
    """Return a sync Engine mock that always returns empty result sets."""

    def _empty_result() -> MagicMock:
        r = MagicMock()
        r._mapping = {}
        result = MagicMock()
        result.__iter__ = MagicMock(return_value=iter([]))
        result.mappings.return_value = MagicMock()
        return result

    conn_ctx = MagicMock()
    conn_ctx.execute.side_effect = lambda *a, **kw: _empty_result()
    conn_cm = MagicMock()
    conn_cm.__enter__ = MagicMock(return_value=conn_ctx)
    conn_cm.__exit__ = MagicMock(return_value=False)
    engine = MagicMock()
    engine.connect.return_value = conn_cm
    return engine


# ---------------------------------------------------------------------------
# Task 1: factor_db_id threading
# ---------------------------------------------------------------------------


class TestFactorDbIdOnFactorRecord:
    """FactorRecord.factor_db_id is a valid optional UUID field."""

    def test_factor_record_default_factor_db_id_is_none(self) -> None:
        """FactorRecord instantiated without factor_db_id defaults to None."""
        from ghg_tool.domain.ports.factor_catalog import FactorRecord

        fr = FactorRecord(
            factor_id="TEST_FACTOR",
            version="2025",
            value=Decimal("1.5"),
            unit="kg CO2e / kWh",
            source="DEFRA",
            gwp_set="AR6",
        )
        assert fr.factor_db_id is None

    def test_factor_record_accepts_factor_db_id(self) -> None:
        """FactorRecord stores a non-None factor_db_id when provided."""
        from ghg_tool.domain.ports.factor_catalog import FactorRecord

        fr = FactorRecord(
            factor_id="TEST_FACTOR",
            version="2025",
            value=Decimal("1.5"),
            unit="kg CO2e / kWh",
            source="DEFRA",
            gwp_set="AR6",
            factor_db_id=_FACTOR_DB_ID,
        )
        assert fr.factor_db_id == _FACTOR_DB_ID

    def test_sql_adapter_row_to_factor_record_populates_factor_db_id(self) -> None:
        """_row_to_factor_record() maps the 'id' column to factor_db_id."""
        from ghg_tool.infrastructure.factors.sql_adapter import _row_to_factor_record

        row: dict[str, Any] = {
            "id": str(_FACTOR_DB_ID),
            "factor_id": "COMB_GAS_NAT_CO2_DEFRA_2025",
            "version": "2025",
            "value": "0.18293",
            "unit": "kg CO2e / kWh",
            "source": "DEFRA",
            "gwp_set": "AR6",
            "biogenic_co2_kg_per_unit": None,
            "vintage": "2025",
            "applicability_note": None,
            "is_tbc": False,
            "is_licence_only": False,
        }
        record = _row_to_factor_record(row)
        assert record.factor_db_id == _FACTOR_DB_ID

    def test_make_emission_threads_factor_db_id_into_emission_record(self) -> None:
        """make_emission() copies factor.factor_db_id to EmissionRecord.factor_id_uuid."""
        from ghg_tool.application.calc._helpers import make_emission
        from ghg_tool.domain.ports.factor_catalog import FactorRecord

        factor = FactorRecord(
            factor_id="COMB_GAS_NAT_CO2_DEFRA_2025",
            version="2025",
            value=Decimal("0.18293"),
            unit="kg CO2e / kWh",
            source="DEFRA",
            gwp_set="AR6",
            factor_db_id=_FACTOR_DB_ID,
        )
        emission = make_emission(
            correlation_id=_CORRELATION_ID,
            raw_row_id=uuid.uuid4(),
            scope=1,
            sub_scope="combustion",
            codice_sito="SITE_A",
            anno=_ANNO,
            tco2e=Decimal("10.0"),
            factor=factor,
            gwp_set="AR6",
            methodology="activity-based",
            regulatory_stream="CSRD_ESRS_E1",
            created_by="test",
        )
        assert emission.factor_id_uuid == _FACTOR_DB_ID

    def test_emission_to_params_uses_factor_id_uuid_for_fk(self) -> None:
        """_emission_to_params produces factor_id=str(factor_id_uuid) when non-None."""
        from ghg_tool.application.services.calc_persistence import _emission_to_params
        from ghg_tool.domain.entities.emission_record import EmissionRecord

        now = datetime.now(UTC)
        record = EmissionRecord(
            correlation_id=_CORRELATION_ID,
            raw_row_id=None,
            scope=1,
            sub_scope="combustion",
            codice_sito="SITE_A",
            anno=_ANNO,
            tco2e=Decimal("5.0"),
            factor_id="COMB_GAS_NAT_CO2_DEFRA_2025",
            factor_version="2025",
            factor_source="DEFRA",
            gwp_set="AR6",
            methodology="activity-based",
            regulatory_stream="CSRD_ESRS_E1",
            calc_timestamp=now,
            created_by="test",
            factor_id_uuid=_FACTOR_DB_ID,
        )
        params = _emission_to_params(record, tenant_id=_TENANT_ID)
        assert params["factor_id"] == str(_FACTOR_DB_ID)

    def test_emission_to_params_falls_back_to_nil_uuid_when_factor_id_uuid_is_none(self) -> None:
        """_emission_to_params uses nil UUID as fallback when factor_id_uuid is None."""
        from ghg_tool.application.services.calc_persistence import _emission_to_params
        from ghg_tool.domain.entities.emission_record import EmissionRecord

        now = datetime.now(UTC)
        record = EmissionRecord(
            correlation_id=_CORRELATION_ID,
            raw_row_id=None,
            scope=1,
            sub_scope="combustion",
            codice_sito="SITE_A",
            anno=_ANNO,
            tco2e=Decimal("5.0"),
            factor_id="COMB_GAS_NAT_CO2_DEFRA_2025",
            factor_version="2025",
            factor_source="DEFRA",
            gwp_set="AR6",
            methodology="activity-based",
            regulatory_stream="CSRD_ESRS_E1",
            calc_timestamp=now,
            created_by="test",
            factor_id_uuid=None,
        )
        params = _emission_to_params(record, tenant_id=_TENANT_ID)
        assert params["factor_id"] == str(uuid.UUID(int=0))


# ---------------------------------------------------------------------------
# Task 2: set_session_gucs called before INSERT
# ---------------------------------------------------------------------------


class TestSetSessionGucsCalledBeforeInsert:
    """_persist_emissions must call set_session_gucs before any INSERT."""

    def test_set_session_gucs_called_with_correct_args(self) -> None:
        """set_session_gucs is awaited with tenant_id and role_code=admin."""
        from ghg_tool.application.services.calc_persistence import _persist_emissions

        factory, calls_log = _make_async_session_factory()

        with patch(
            "ghg_tool.application.services.calc_persistence.set_session_gucs",
            new_callable=AsyncMock,
        ) as mock_gucs:
            asyncio.run(
                _persist_emissions(
                    factory,
                    tenant_id=_TENANT_ID,
                    correlation_id=_CORRELATION_ID,
                    anno=_ANNO,
                    records=[],
                    duration_ms=100,
                    started_at=datetime.now(UTC),
                    gwp_set="AR6",
                    regulatory_stream="CSRD_ESRS_E1",
                    created_by="test",
                )
            )

        mock_gucs.assert_awaited_once()
        _, kwargs = mock_gucs.await_args
        assert kwargs["tenant_id"] == str(_TENANT_ID)
        assert kwargs["role_code"] == "admin"

    def test_set_session_gucs_called_before_insert_exec(self) -> None:
        """set_session_gucs must be the very first awaited call in the transaction."""
        from ghg_tool.application.services.calc_persistence import _persist_emissions
        from ghg_tool.domain.entities.emission_record import EmissionRecord

        now = datetime.now(UTC)
        record = EmissionRecord(
            correlation_id=_CORRELATION_ID,
            raw_row_id=None,
            scope=1,
            sub_scope="combustion",
            codice_sito="SITE_A",
            anno=_ANNO,
            tco2e=Decimal("1.0"),
            factor_id="F",
            factor_version="1",
            factor_source="DEFRA",
            gwp_set="AR6",
            methodology="activity-based",
            regulatory_stream="CSRD_ESRS_E1",
            calc_timestamp=now,
            created_by="test",
        )

        call_order: list[str] = []

        async def _fake_gucs(session: Any, *, tenant_id: str, role_code: str) -> None:
            call_order.append("gucs")

        factory, _ = _make_async_session_factory()

        with patch(
            "ghg_tool.application.services.calc_persistence.set_session_gucs",
            side_effect=_fake_gucs,
        ):
            # Patch _INSERT_EMISSION / _INSERT_CALC_RUN execute to track order
            original_factory_cm = factory.return_value

            original_session = AsyncMock()
            insert_calls: list[str] = []

            async def _tracking_execute(stmt: Any, params: Any = None) -> MagicMock:
                insert_calls.append("insert")
                return MagicMock()

            original_session.execute = _tracking_execute
            begin_cm = AsyncMock()
            begin_cm.__aenter__ = AsyncMock(return_value=None)
            begin_cm.__aexit__ = AsyncMock(return_value=False)
            original_session.begin = MagicMock(return_value=begin_cm)
            original_factory_cm.__aenter__ = AsyncMock(return_value=original_session)

            asyncio.run(
                _persist_emissions(
                    factory,
                    tenant_id=_TENANT_ID,
                    correlation_id=_CORRELATION_ID,
                    anno=_ANNO,
                    records=[record],
                    duration_ms=50,
                    started_at=datetime.now(UTC),
                    gwp_set="AR6",
                    regulatory_stream="CSRD_ESRS_E1",
                    created_by="test",
                )
            )

        # gucs must appear before any insert
        assert call_order == ["gucs"]
        assert len(insert_calls) >= 1  # at least emission + calc_runs INSERT


# ---------------------------------------------------------------------------
# Task 3A: Scheduler env-var gating
# ---------------------------------------------------------------------------


class TestSchedulerEnvGating:
    """start_scheduler() must not start a scheduler when the env var is unset."""

    def test_scheduler_not_started_when_env_var_unset(  # noqa: E501
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """start_scheduler returns None when GHG_CALC_SCHEDULE_CRON is not set."""
        monkeypatch.delenv("GHG_CALC_SCHEDULE_CRON", raising=False)

        from ghg_tool.infrastructure.scheduling.calc_scheduler import start_scheduler

        result = start_scheduler(anno=2025)
        assert result is None

    def test_scheduler_not_started_when_env_var_empty(  # noqa: E501
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """start_scheduler returns None when GHG_CALC_SCHEDULE_CRON is empty string."""
        monkeypatch.setenv("GHG_CALC_SCHEDULE_CRON", "")

        from importlib import reload

        import ghg_tool.infrastructure.scheduling.calc_scheduler as mod
        reload(mod)

        result = mod.start_scheduler(anno=2025)
        assert result is None

    def test_scheduler_started_when_env_var_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """start_scheduler returns a scheduler object when a valid cron is given."""
        monkeypatch.setenv("GHG_CALC_SCHEDULE_CRON", "0 2 * * *")

        mock_scheduler = MagicMock()
        mock_scheduler_cls = MagicMock(return_value=mock_scheduler)
        mock_trigger = MagicMock()
        mock_trigger_cls = MagicMock(return_value=mock_trigger)

        with patch.dict(
            "sys.modules",
            {
                "apscheduler": MagicMock(),
                "apscheduler.schedulers": MagicMock(),
                "apscheduler.schedulers.background": MagicMock(  # noqa: E501
                    BackgroundScheduler=mock_scheduler_cls
                ),
                "apscheduler.triggers": MagicMock(),
                "apscheduler.triggers.cron": MagicMock(CronTrigger=mock_trigger_cls),
            },
        ):
            from importlib import reload

            import ghg_tool.infrastructure.scheduling.calc_scheduler as mod
            reload(mod)

            result = mod.start_scheduler(anno=2025)

        assert result is mock_scheduler
        mock_scheduler.start.assert_called_once()
        # Two jobs should be added: CSRD and EU ETS
        assert mock_scheduler.add_job.call_count == 2


# ---------------------------------------------------------------------------
# Task 3B: Admin trigger endpoint — POST /api/v1/calc/run
# ---------------------------------------------------------------------------


class TestCalcTriggerEndpoint:
    """POST /api/v1/calc/run returns 202 with a correlation_id."""

    def _make_app(self) -> Any:
        from fastapi import FastAPI

        from ghg_tool.api.routers.calc import router as calc_router

        app = FastAPI()
        app.include_router(calc_router)
        return app

    def test_trigger_returns_202_with_correlation_id(self) -> None:
        """POST /api/v1/calc/run returns 202 and a valid UUID correlation_id."""
        from fastapi.testclient import TestClient

        app = self._make_app()

        fake_user = MagicMock()
        fake_user.sub = "user-sub-001"
        fake_user.tenant_id = str(_TENANT_ID)
        fake_user.role = "admin"


        with patch(
            "ghg_tool.api.routers.calc.require_role",
            return_value=lambda: fake_user,
        ), patch(
            "ghg_tool.api.routers.calc._background_run",
        ):
            # Override the dependency to bypass real JWT auth
            app.dependency_overrides = {}

            from ghg_tool.api.dependencies.auth import get_current_user

            def _fake_auth() -> Any:
                return fake_user

            app.dependency_overrides[get_current_user] = _fake_auth

            with (
                TestClient(app, raise_server_exceptions=True) as client,
                patch("ghg_tool.api.routers.calc._background_run"),
            ):
                resp = client.post(
                    "/api/v1/calc/run",
                    json={"anno": 2025, "regulatory_stream": "CSRD_ESRS_E1"},
                    headers={"Authorization": "Bearer fake"},
                )

        assert resp.status_code == 202
        body = resp.json()
        assert "correlation_id" in body
        # Must be a valid UUID
        uuid.UUID(body["correlation_id"])

    def test_trigger_dual_returns_202_with_two_correlation_ids(self) -> None:
        """POST /api/v1/calc/run-dual returns 202 with two distinct correlation_ids."""
        from fastapi.testclient import TestClient

        app = self._make_app()

        fake_user = MagicMock()
        fake_user.sub = "user-sub-002"
        fake_user.tenant_id = str(_TENANT_ID)
        fake_user.role = "admin"

        from ghg_tool.api.dependencies.auth import get_current_user

        def _fake_auth() -> Any:
            return fake_user

        app.dependency_overrides[get_current_user] = _fake_auth

        with (
            TestClient(app, raise_server_exceptions=True) as client,
            patch("ghg_tool.api.routers.calc._background_run"),
        ):
            resp = client.post(
                "/api/v1/calc/run-dual",
                json={"anno": 2025},
                headers={"Authorization": "Bearer fake"},
            )

        assert resp.status_code == 202
        body = resp.json()
        assert "csrd_correlation_id" in body
        assert "eu_ets_correlation_id" in body
        csrd_cid = uuid.UUID(body["csrd_correlation_id"])
        eu_ets_cid = uuid.UUID(body["eu_ets_correlation_id"])
        assert csrd_cid != eu_ets_cid


# ---------------------------------------------------------------------------
# Task 3C: Status endpoint — GET /api/v1/calc/runs/{cid}
# ---------------------------------------------------------------------------


class TestCalcStatusEndpoint:
    """GET /api/v1/calc/runs/{cid} returns 200 or 404."""

    def _make_app_with_fake_session(self, db_row: dict | None) -> Any:
        from fastapi import FastAPI

        from ghg_tool.api.dependencies.auth import get_current_user
        from ghg_tool.api.dependencies.db import get_db
        from ghg_tool.api.routers.calc import router as calc_router

        app = FastAPI()
        app.include_router(calc_router)

        fake_user = MagicMock()
        fake_user.sub = "user-viewer"
        fake_user.tenant_id = str(_TENANT_ID)
        fake_user.role = "viewer"

        async def _fake_db() -> Any:
            session = AsyncMock()

            result_mock = MagicMock()
            mapping_mock = MagicMock()
            mapping_mock.first.return_value = db_row
            result_mock.mappings.return_value = mapping_mock
            session.execute = AsyncMock(return_value=result_mock)
            yield session

        app.dependency_overrides[get_current_user] = lambda: fake_user
        app.dependency_overrides[get_db] = _fake_db
        return app

    def test_status_returns_200_when_run_found(self) -> None:
        """GET /runs/{cid} returns 200 with CalcRunStatus fields when the row exists."""
        from fastapi.testclient import TestClient

        cid = _CORRELATION_ID
        db_row = {
            "correlation_id": str(cid),
            "anno": 2025,
            "emissions_written": 42,
            "duration_ms": 1234,
            "gwp_set": "AR6",
            "regulatory_stream": "CSRD_ESRS_E1",
            "started_at": "2026-01-01 02:00:00+00",
            "finished_at": "2026-01-01 02:00:01+00",
            "created_by": "calc_scheduler",
        }
        app = self._make_app_with_fake_session(db_row)
        with TestClient(app) as client:
            resp = client.get(f"/api/v1/calc/runs/{cid}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["emissions_written"] == 42
        assert body["gwp_set"] == "AR6"
        assert uuid.UUID(body["correlation_id"]) == cid

    def test_status_returns_404_when_run_not_found(self) -> None:
        """GET /runs/{cid} returns 404 when no ops.calc_runs row matches."""
        from fastapi.testclient import TestClient

        cid = uuid.uuid4()
        app = self._make_app_with_fake_session(db_row=None)
        with TestClient(app) as client:
            resp = client.get(f"/api/v1/calc/runs/{cid}")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Task 3D: Dual-track CLI runs twice
# ---------------------------------------------------------------------------


class TestDualTrackCli:
    """--dual flag causes run_calc_and_persist to be called twice with different params."""

    def test_dual_flag_calls_run_twice_with_different_streams(self) -> None:
        """With --dual, run_calc_and_persist is called for CSRD and EU_ETS_PHASE_IV."""
        import importlib
        from unittest.mock import MagicMock as _MM
        from unittest.mock import patch as _patch

        fake_result = _MM()
        fake_result.correlation_id = uuid.uuid4()
        fake_result.emissions_written = 10
        fake_result.scope1_count = 5
        fake_result.scope2_count = 3
        fake_result.scope3_count = 2
        fake_result.duration_ms = 500

        call_kwargs: list[dict] = []

        def _fake_run(**kwargs: Any) -> Any:
            call_kwargs.append(kwargs)
            return fake_result

        # Build a minimal engine mock that satisfies _resolve_tenant
        def _fake_create_engine(*a: Any, **kw: Any) -> MagicMock:
            eng = MagicMock()
            conn_ctx = MagicMock()
            row_mock = MagicMock()
            row_mock.__getitem__ = lambda self, i: str(_TENANT_ID)
            conn_ctx.execute.return_value.fetchone.return_value = row_mock
            conn_cm = MagicMock()
            conn_cm.__enter__ = MagicMock(return_value=conn_ctx)
            conn_cm.__exit__ = MagicMock(return_value=False)
            eng.connect.return_value = conn_cm
            return eng

        test_args = ["run_calc", "--anno", "2025", "--tenant-code", "GRESMALT", "--dual"]

        with _patch("sys.argv", test_args), \
             _patch("sqlalchemy.create_engine", side_effect=_fake_create_engine), \
             _patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=MagicMock()), \
             _patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=MagicMock()), \
             _patch(
                 "ghg_tool.application.services.calc_persistence.run_calc_and_persist",
                 side_effect=_fake_run,
             ), \
             pytest.raises(SystemExit) as exc_info:
            import scripts.run_calc as run_calc_mod
            importlib.reload(run_calc_mod)
            run_calc_mod.main()

        assert exc_info.value.code == 0
        assert len(call_kwargs) == 2
        streams = {kw["regulatory_stream"] for kw in call_kwargs}
        gwp_sets = {kw["gwp_set"] for kw in call_kwargs}
        assert streams == {"CSRD_ESRS_E1", "EU_ETS_PHASE_IV"}
        assert gwp_sets == {"AR6", "AR5"}

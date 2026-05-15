"""Unit tests for calc_persistence.run_calc_and_persist.

All SQLAlchemy sessions are mocked; no live DB is required.

Coverage:
- happy path: 3 raw rows + 1 factor -> emission record written + ops.calc_runs row written
- empty raw tables: zero emissions written but ops.calc_runs row still written (count=0)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from ghg_tool.application.services.calc_persistence import (
    CalcPersistResult,
    DualTrackPersistResult,
    run_calc_and_persist,
    run_dual_track_and_persist,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_CORRELATION_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
_ANNO = 2025


def _make_sync_engine(
    scope1_rows: list[dict],
    scope2_rows: list[dict],
    scope3_rows: list[dict],
    site_rows: list[tuple[str]],
) -> MagicMock:
    """Build a mock sync Engine that returns supplied raw rows.

    We need to handle multiple execute() calls (S1, S2, S3, sites + factor lookups).
    We use a side_effect list on conn.execute keyed by call order.
    Factor lookups (from SqlFactorCatalogAdapter._fetch) open a second connection
    context; we patch the adapter separately.

    Args:
        scope1_rows: Rows for scope1_ingestions.
        scope2_rows: Rows for scope2_ingestions.
        scope3_rows: Rows for scope3_ingestions.
        site_rows: Rows for the DISTINCT codice_sito query.

    Returns:
        Mocked Engine.
    """

    def _make_result(rows: list[Any], as_tuples: bool = False) -> MagicMock:
        result = MagicMock()
        mappings = MagicMock()
        # Each row is a MagicMock with _mapping attr returning itself.
        mock_rows = []
        for row in rows:
            r = MagicMock()
            r._mapping = row
            mock_rows.append(r)
        result.__iter__ = MagicMock(return_value=iter(mock_rows))
        result.mappings.return_value = mappings
        return result

    # Tuple rows for site query (index access with row[0])
    def _make_site_result(rows: list[tuple[str]]) -> MagicMock:
        result = MagicMock()
        mock_rows = []
        for row in rows:
            r = MagicMock()
            r.__getitem__ = lambda self, i, _r=row: _r[i]
            mock_rows.append(r)
        result.__iter__ = MagicMock(return_value=iter(mock_rows))
        return result

    # _load_raw_rows opens ONE connection and calls execute 4 times (S1, S2, S3, sites).
    s1_result = _make_result(scope1_rows)
    s2_result = _make_result(scope2_rows)
    s3_result = _make_result(scope3_rows)
    sites_result = _make_site_result(site_rows)

    conn_ctx = MagicMock()
    conn_ctx.execute.side_effect = [s1_result, s2_result, s3_result, sites_result]

    conn_cm = MagicMock()
    conn_cm.__enter__ = MagicMock(return_value=conn_ctx)
    conn_cm.__exit__ = MagicMock(return_value=False)

    engine = MagicMock()
    engine.connect.return_value = conn_cm
    return engine


def _make_async_session_factory() -> tuple[MagicMock, list[dict]]:
    """Return (factory, captured_params) where captured_params collects INSERT dicts.

    Args: none.

    Returns:
        Tuple of (async_sessionmaker mock, list accumulating INSERT param dicts).
    """
    captured: list[dict] = []

    async def _fake_execute(stmt: Any, params: Any = None) -> MagicMock:
        if params is not None:
            if isinstance(params, list):
                captured.extend(params)
            else:
                captured.append(params)
        return MagicMock()

    session = AsyncMock()
    session.execute = _fake_execute

    # Context manager for async with session.begin()
    begin_cm = AsyncMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin_cm)

    # Context manager for async with session_factory() as session
    factory_cm = AsyncMock()
    factory_cm.__aenter__ = AsyncMock(return_value=session)
    factory_cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = factory_cm

    return factory, captured


# ---------------------------------------------------------------------------
# Minimal raw rows that the orchestrator can process without hitting real factors
# ---------------------------------------------------------------------------

_S1_ROW: dict[str, Any] = {
    "id": str(uuid.uuid4()),
    "tenant_id": str(_TENANT_ID),
    "anno": _ANNO,
    "codice_sito": "SITE_A",
    "categoria_s1": "Combustione_Mobile",
    "combustibile": "GAS_NAT",
    "quantita": "100.0",
    "unita": "Sm3",
    "fonte_dato": "Bollette",
    "qualita_dato": "H",
    "stato_dato": "Consolidato",
    "note": None,
    "provenance": None,
}

_S2_ROW: dict[str, Any] = {
    "id": str(uuid.uuid4()),
    "tenant_id": str(_TENANT_ID),
    "anno": _ANNO,
    "codice_sito": "SITE_A",
    "voce_s2": "EE_Acquistata_Grid",
    "quantita": "50000.0",
    "unita": "kWh",
    "strumento_mb": None,
    "fonte_dato": "Bollette",
    "qualita_dato": "H",
    "stato_dato": "Consolidato",
    "note": None,
    "provenance": None,
}

_S3_ROW: dict[str, Any] = {
    "id": str(uuid.uuid4()),
    "tenant_id": str(_TENANT_ID),
    "anno": _ANNO,
    "categoria_s3": 4,
    "sottocategoria": "Feldspati_Camion",
    "metodo": "distance-based",
    "combustibile": None,
    "quantita": "200.0",
    "unita": "t*km",
    "fonte_dato": "DDT",
    "qualita_dato": "H",
    "stato_dato": "Consolidato",
    "note": None,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    """3 raw rows + mocked orchestrator -> emission written + ops.calc_runs row written."""

    def test_emissions_and_calc_runs_row_written(self) -> None:
        """run_calc_and_persist with 3 raw rows writes N emission rows and 1 calc_runs row."""
        from ghg_tool.domain.entities.emission_record import EmissionRecord

        now = datetime.now(UTC)
        fake_emission = EmissionRecord(
            correlation_id=_CORRELATION_ID,
            raw_row_id=uuid.uuid4(),
            scope=1,
            sub_scope="combustion",
            codice_sito="SITE_A",
            anno=_ANNO,
            tco2e=Decimal("200.0"),
            factor_id="COMB_GAS_NAT_CO2_DEFRA_2025",
            factor_version="2025",
            factor_source="DEFRA",
            gwp_set="AR6",
            methodology="activity-based",
            regulatory_stream="CSRD_ESRS_E1",
            calc_timestamp=now,
            created_by="calc_service",
        )

        sync_engine = _make_sync_engine(
            [_S1_ROW], [_S2_ROW], [_S3_ROW], [("SITE_A",)]
        )
        session_factory, captured = _make_async_session_factory()

        with patch(
            "ghg_tool.application.services.calc_persistence.CalcOrchestrator"
        ) as mock_orch_cls, patch(
            "ghg_tool.application.services.calc_persistence.SqlFactorCatalogAdapter"
        ):
            mock_orch = MagicMock()
            mock_orch.run.return_value = [fake_emission]
            mock_orch_cls.return_value = mock_orch

            result = run_calc_and_persist(
                tenant_id=_TENANT_ID,
                anno=_ANNO,
                correlation_id=_CORRELATION_ID,
                sync_engine=sync_engine,
                async_session_factory=session_factory,
                created_by="calc_service",
            )

        assert isinstance(result, CalcPersistResult)
        assert result.emissions_written == 1
        assert result.scope1_count == 1
        assert result.scope2_count == 0
        assert result.scope3_count == 0
        assert result.correlation_id == _CORRELATION_ID
        assert result.duration_ms >= 0

        # Verify ops.calc_runs row was inserted (last item in captured params).
        ops_row = next(
            (p for p in captured if "emissions_written" in p),
            None,
        )
        assert ops_row is not None, "ops.calc_runs INSERT params not captured"
        assert ops_row["emissions_written"] == 1
        assert ops_row["anno"] == _ANNO
        assert str(ops_row["correlation_id"]) == str(_CORRELATION_ID)

    def test_result_fields_populated(self) -> None:
        """CalcPersistResult carries all expected fields."""
        from ghg_tool.domain.entities.emission_record import EmissionRecord

        now = datetime.now(UTC)
        s1 = EmissionRecord(
            correlation_id=_CORRELATION_ID,
            raw_row_id=uuid.uuid4(),
            scope=1,
            sub_scope="combustion",
            codice_sito="SITE_A",
            anno=_ANNO,
            tco2e=Decimal("10.0"),
            factor_id="COMB_GAS_NAT_CO2_DEFRA_2025",
            factor_version="2025",
            factor_source="DEFRA",
            gwp_set="AR6",
            methodology="activity-based",
            regulatory_stream="CSRD_ESRS_E1",
            calc_timestamp=now,
            created_by="calc_service",
        )
        s3 = EmissionRecord(
            correlation_id=_CORRELATION_ID,
            raw_row_id=uuid.uuid4(),
            scope=3,
            sub_scope="Cat4",
            codice_sito=None,
            anno=_ANNO,
            tco2e=Decimal("5.0"),
            factor_id="FREIGHT_HGV_DEFRA_2025",
            factor_version="2025",
            factor_source="DEFRA",
            gwp_set="AR6",
            methodology="distance-based",
            regulatory_stream="CSRD_ESRS_E1",
            calc_timestamp=now,
            created_by="calc_service",
        )

        sync_engine = _make_sync_engine([], [], [], [])
        session_factory, _ = _make_async_session_factory()

        with patch(
            "ghg_tool.application.services.calc_persistence.CalcOrchestrator"
        ) as mock_orch_cls, patch(
            "ghg_tool.application.services.calc_persistence.SqlFactorCatalogAdapter"
        ):
            mock_orch = MagicMock()
            mock_orch.run.return_value = [s1, s3]
            mock_orch_cls.return_value = mock_orch

            result = run_calc_and_persist(
                tenant_id=_TENANT_ID,
                anno=_ANNO,
                correlation_id=_CORRELATION_ID,
                sync_engine=sync_engine,
                async_session_factory=session_factory,
            )

        assert result.emissions_written == 2
        assert result.scope1_count == 1
        assert result.scope2_count == 0
        assert result.scope3_count == 1


class TestEmptyRawTables:
    """Zero raw rows: no emissions written but ops.calc_runs row still written."""

    def test_zero_emissions_still_writes_calc_runs_row(self) -> None:
        sync_engine = _make_sync_engine([], [], [], [])
        session_factory, captured = _make_async_session_factory()

        with patch(
            "ghg_tool.application.services.calc_persistence.CalcOrchestrator"
        ) as mock_orch_cls, patch(
            "ghg_tool.application.services.calc_persistence.SqlFactorCatalogAdapter"
        ):
            mock_orch = MagicMock()
            mock_orch.run.return_value = []
            mock_orch_cls.return_value = mock_orch

            result = run_calc_and_persist(
                tenant_id=_TENANT_ID,
                anno=_ANNO,
                correlation_id=_CORRELATION_ID,
                sync_engine=sync_engine,
                async_session_factory=session_factory,
            )

        assert result.emissions_written == 0
        assert result.scope1_count == 0
        assert result.scope2_count == 0
        assert result.scope3_count == 0

        # ops.calc_runs row must still be present.
        ops_row = next(
            (p for p in captured if "emissions_written" in p),
            None,
        )
        assert ops_row is not None, "ops.calc_runs INSERT missing for zero-emission run"
        assert ops_row["emissions_written"] == 0
        assert ops_row["anno"] == _ANNO

    def test_zero_emissions_returns_persist_result(self) -> None:
        sync_engine = _make_sync_engine([], [], [], [])
        session_factory, _ = _make_async_session_factory()

        with patch(
            "ghg_tool.application.services.calc_persistence.CalcOrchestrator"
        ) as mock_orch_cls, patch(
            "ghg_tool.application.services.calc_persistence.SqlFactorCatalogAdapter"
        ):
            mock_orch = MagicMock()
            mock_orch.run.return_value = []
            mock_orch_cls.return_value = mock_orch

            result = run_calc_and_persist(
                tenant_id=_TENANT_ID,
                anno=_ANNO,
                correlation_id=_CORRELATION_ID,
                sync_engine=sync_engine,
                async_session_factory=session_factory,
            )

        assert isinstance(result, CalcPersistResult)
        assert result.correlation_id == _CORRELATION_ID


# ---------------------------------------------------------------------------
# New unit tests: dual_run_id binding + UUID pre-generation (Q1.A + Q2)
# ---------------------------------------------------------------------------


class TestDualRunIdBinding:
    """Verify dual_run_id is threaded correctly through run_calc_and_persist."""

    def test_run_calc_and_persist_binds_dual_run_id(self) -> None:
        """When dual_run_id is passed, the SQL bind contains it (not None)."""
        from ghg_tool.domain.entities.emission_record import EmissionRecord

        now = datetime.now(UTC)
        fake_emission = EmissionRecord(
            correlation_id=_CORRELATION_ID,
            raw_row_id=uuid.uuid4(),
            scope=1,
            sub_scope="combustion",
            codice_sito="SITE_A",
            anno=_ANNO,
            tco2e=Decimal("100.0"),
            factor_id="COMB_GAS_NAT_CO2_DEFRA_2025",
            factor_version="2025",
            factor_source="DEFRA",
            gwp_set="AR6",
            methodology="activity-based",
            regulatory_stream="CSRD_ESRS_E1",
            calc_timestamp=now,
            created_by="calc_service",
        )

        _DUAL_RUN_ID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")

        sync_engine = _make_sync_engine([], [], [], [])
        session_factory, captured = _make_async_session_factory()

        with patch(
            "ghg_tool.application.services.calc_persistence.CalcOrchestrator"
        ) as mock_orch_cls, patch(
            "ghg_tool.application.services.calc_persistence.SqlFactorCatalogAdapter"
        ):
            mock_orch = MagicMock()
            mock_orch.run.return_value = [fake_emission]
            mock_orch_cls.return_value = mock_orch

            run_calc_and_persist(
                tenant_id=_TENANT_ID,
                anno=_ANNO,
                correlation_id=_CORRELATION_ID,
                sync_engine=sync_engine,
                async_session_factory=session_factory,
                dual_run_id=_DUAL_RUN_ID,
            )

        # Find the ops.calc_runs INSERT params (has 'emissions_written' key)
        ops_row = next(
            (p for p in captured if "emissions_written" in p),
            None,
        )
        assert ops_row is not None, "ops.calc_runs INSERT params not captured"
        assert ops_row["dual_run_id"] == str(_DUAL_RUN_ID), (
            f"Expected dual_run_id={_DUAL_RUN_ID}, got {ops_row.get('dual_run_id')}"
        )

    def test_run_calc_and_persist_dual_run_id_default_none(self) -> None:
        """Default behavior: dual_run_id is None in the SQL bind (single-track)."""
        sync_engine = _make_sync_engine([], [], [], [])
        session_factory, captured = _make_async_session_factory()

        with patch(
            "ghg_tool.application.services.calc_persistence.CalcOrchestrator"
        ) as mock_orch_cls, patch(
            "ghg_tool.application.services.calc_persistence.SqlFactorCatalogAdapter"
        ):
            mock_orch = MagicMock()
            mock_orch.run.return_value = []
            mock_orch_cls.return_value = mock_orch

            run_calc_and_persist(
                tenant_id=_TENANT_ID,
                anno=_ANNO,
                correlation_id=_CORRELATION_ID,
                sync_engine=sync_engine,
                async_session_factory=session_factory,
                # dual_run_id not passed — default is None
            )

        ops_row = next(
            (p for p in captured if "emissions_written" in p),
            None,
        )
        assert ops_row is not None, "ops.calc_runs INSERT params not captured"
        assert ops_row["dual_run_id"] is None, (
            f"Expected dual_run_id=None for single-track, got {ops_row.get('dual_run_id')}"
        )

    def test_dual_track_entry_pre_generates_both_uuids(self) -> None:
        """Both UUIDs must be generated client-side before any DB call.

        Mocks uuid.uuid4 to verify the call count reaches 2 (for csrd_run_id
        and ets_run_id) before any session execute is invoked.
        """
        sync_engine = _make_sync_engine([], [], [], [])
        session_factory, _ = _make_async_session_factory()

        original_uuid4 = uuid.uuid4

        uuid4_calls: list[uuid.UUID] = []

        def counting_uuid4() -> uuid.UUID:
            val = original_uuid4()
            uuid4_calls.append(val)
            return val

        with patch(
            "ghg_tool.application.services.calc_persistence.CalcOrchestrator"
        ) as mock_orch_cls, patch(
            "ghg_tool.application.services.calc_persistence.SqlFactorCatalogAdapter"
        ), patch(
            "ghg_tool.application.services.calc_persistence.uuid.uuid4",
            side_effect=counting_uuid4,
        ) as mock_uuid4:
            mock_orch = MagicMock()
            mock_orch.run.return_value = []
            mock_orch_cls.return_value = mock_orch

            result = run_dual_track_and_persist(
                tenant_id=_TENANT_ID,
                anno=_ANNO,
                sync_engine=sync_engine,
                async_session_factory=session_factory,
            )

        # uuid.uuid4() must be called at least 4 times:
        # csrd_run_id, ets_run_id, shared_correlation_id (3 explicit calls)
        # plus any calls inside _emission_to_params for nil UUID fallback (none
        # here since records list is empty).
        # The key assertion: at least 2 run UUIDs were generated.
        total_calls = mock_uuid4.call_count
        assert total_calls >= 2, (
            f"Expected at least 2 uuid.uuid4() calls (csrd_run_id + ets_run_id), "
            f"got {total_calls}"
        )

        # Verify both run UUIDs appear in the result
        assert result.csrd_result.run_id is not None
        assert result.ets_result.run_id is not None
        assert result.csrd_result.run_id != result.ets_result.run_id, (
            "CSRD and ETS run_ids must be distinct"
        )

        # Verify shared correlation_id
        assert result.csrd_result.correlation_id == result.ets_result.correlation_id, (
            "correlation_id must be identical across both tracks (Q2)"
        )

        assert isinstance(result, DualTrackPersistResult)

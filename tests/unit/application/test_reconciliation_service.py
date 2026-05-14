"""Unit tests for reconciliation_service.reconcile (M13).

Pure unit tests: no DB, no Streamlit, no FastAPI.  Every test constructs
two dict-based emission lists and asserts on the ReconciliationResult.
"""

from __future__ import annotations

from decimal import Decimal

from ghg_tool.application.services.reconciliation_service import (
    CAUSE_DATA_CORRECTION,
    CAUSE_FACTOR_UPDATE,
    CAUSE_NEW_ROW,
    CAUSE_UNKNOWN,
    CAUSE_WITHDRAWN_ROW,
    reconcile,
)


def _row(
    *,
    scope: int,
    sub_scope: str,
    codice_sito: str | None,
    anno: int,
    tco2e: str,
    factor_version: str = "v1.0",
) -> dict:
    return {
        "scope": scope,
        "sub_scope": sub_scope,
        "codice_sito": codice_sito,
        "anno": anno,
        "tco2e": tco2e,
        "factor_version": factor_version,
    }


# ---------------------------------------------------------------------------
# 1. Identical sets -> zero deltas, restatement_required False.
# ---------------------------------------------------------------------------
def test_identical_sets_produce_zero_delta() -> None:
    rows = [
        _row(scope=1, sub_scope="comb", codice_sito="IANO", anno=2024, tco2e="100"),
        _row(scope=2, sub_scope="elec_LB", codice_sito="IANO", anno=2024, tco2e="50"),
    ]
    res = reconcile(snapshot_emissions=rows, current_emissions=rows)
    assert res.total_prior == Decimal("150")
    assert res.total_current == Decimal("150")
    assert res.total_abs_delta == Decimal("0")
    assert res.total_delta_pct == Decimal("0")
    assert res.material_count == 0
    assert res.restatement_required is False
    # Each row is a data_correction candidate but with abs_delta=0
    for d in res.rows:
        assert d.abs_delta == Decimal("0")
        assert d.material is False


# ---------------------------------------------------------------------------
# 2. Single 50 -> 60 change: +20% on one row, abs_delta=10 (below floor).
#    With smaller materiality_tco2e the delta becomes material.
# ---------------------------------------------------------------------------
def test_single_value_change_pct_and_materiality() -> None:
    prior = [_row(scope=1, sub_scope="comb", codice_sito="IANO", anno=2024, tco2e="50")]
    curr = [_row(scope=1, sub_scope="comb", codice_sito="IANO", anno=2024, tco2e="60")]
    res = reconcile(
        snapshot_emissions=prior,
        current_emissions=curr,
        materiality_tco2e=Decimal("5"),
    )
    assert len(res.rows) == 1
    d = res.rows[0]
    assert d.abs_delta == Decimal("10")
    assert d.pct_delta == Decimal("20")
    assert d.material is True
    assert d.cause_category == CAUSE_DATA_CORRECTION
    # Aggregate: 50 -> 60 = +20% > 5% -> restatement_required True
    assert res.restatement_required is True


# ---------------------------------------------------------------------------
# 3. Row added in current not in prior -> 'new_row'.
# ---------------------------------------------------------------------------
def test_new_row_cause() -> None:
    prior: list[dict] = []
    curr = [_row(scope=3, sub_scope="cat1", codice_sito="VIANO", anno=2024, tco2e="200")]
    res = reconcile(snapshot_emissions=prior, current_emissions=curr)
    assert len(res.rows) == 1
    d = res.rows[0]
    assert d.prior_tco2e is None
    assert d.current_tco2e == Decimal("200")
    assert d.abs_delta == Decimal("200")
    assert d.pct_delta is None  # undefined when prior is None
    assert d.cause_category == CAUSE_NEW_ROW
    assert d.material is True  # >= materiality_tco2e default 100


# ---------------------------------------------------------------------------
# 4. Row removed in current present in prior -> 'withdrawn_row'.
# ---------------------------------------------------------------------------
def test_withdrawn_row_cause() -> None:
    prior = [_row(scope=2, sub_scope="elec_MB", codice_sito="IANO", anno=2024, tco2e="120")]
    curr: list[dict] = []
    res = reconcile(snapshot_emissions=prior, current_emissions=curr)
    assert len(res.rows) == 1
    d = res.rows[0]
    assert d.prior_tco2e == Decimal("120")
    assert d.current_tco2e is None
    assert d.abs_delta == Decimal("-120")
    assert d.cause_category == CAUSE_WITHDRAWN_ROW
    assert d.material is True


# ---------------------------------------------------------------------------
# 5. factor_version differs -> 'factor_update'.
# ---------------------------------------------------------------------------
def test_factor_update_cause() -> None:
    prior = [
        _row(
            scope=1,
            sub_scope="comb",
            codice_sito="IANO",
            anno=2024,
            tco2e="100",
            factor_version="DEFRA_2023",
        )
    ]
    curr = [
        _row(
            scope=1,
            sub_scope="comb",
            codice_sito="IANO",
            anno=2024,
            tco2e="103",
            factor_version="DEFRA_2024",
        )
    ]
    res = reconcile(snapshot_emissions=prior, current_emissions=curr)
    d = res.rows[0]
    assert d.cause_category == CAUSE_FACTOR_UPDATE
    assert d.abs_delta == Decimal("3")


# ---------------------------------------------------------------------------
# 6. Multi-row scenario: cause_breakdown sums abs_delta correctly.
# ---------------------------------------------------------------------------
def test_multi_row_cause_breakdown_sums() -> None:
    prior = [
        _row(scope=1, sub_scope="comb", codice_sito="A", anno=2024, tco2e="100",
             factor_version="v1"),
        _row(scope=2, sub_scope="elec_LB", codice_sito="A", anno=2024, tco2e="50",
             factor_version="v1"),
        _row(scope=3, sub_scope="cat1", codice_sito="B", anno=2024, tco2e="80",
             factor_version="v1"),
    ]
    curr = [
        # factor_update on row 1: abs_delta = +10
        _row(scope=1, sub_scope="comb", codice_sito="A", anno=2024, tco2e="110",
             factor_version="v2"),
        # data_correction on row 2: abs_delta = -5
        _row(scope=2, sub_scope="elec_LB", codice_sito="A", anno=2024, tco2e="45",
             factor_version="v1"),
        # row 3 withdrawn (not in curr): abs_delta = -80
        # new row added on cat6: abs_delta = +25
        _row(scope=3, sub_scope="cat6", codice_sito="C", anno=2024, tco2e="25",
             factor_version="v1"),
    ]
    res = reconcile(
        snapshot_emissions=prior,
        current_emissions=curr,
        materiality_tco2e=Decimal("1"),
    )
    cb = res.cause_breakdown
    assert cb[CAUSE_FACTOR_UPDATE] == Decimal("10")
    assert cb[CAUSE_DATA_CORRECTION] == Decimal("5")
    assert cb[CAUSE_WITHDRAWN_ROW] == Decimal("80")
    assert cb[CAUSE_NEW_ROW] == Decimal("25")
    # No unknowns produced when factor_version is provided everywhere.
    assert cb[CAUSE_UNKNOWN] == Decimal("0")


# ---------------------------------------------------------------------------
# 7. Aggregate below threshold but a single row above 2x threshold ->
#    restatement_required True.
# ---------------------------------------------------------------------------
def test_single_row_above_2x_threshold_forces_restatement() -> None:
    # Large stable base so the aggregate pct stays below 5%.
    prior = [
        _row(scope=1, sub_scope="comb", codice_sito="A", anno=2024, tco2e="10000"),
        _row(scope=1, sub_scope="comb", codice_sito="B", anno=2024, tco2e="500"),
    ]
    curr = [
        _row(scope=1, sub_scope="comb", codice_sito="A", anno=2024, tco2e="10100"),
        # +50% on row B -> abs_delta=250, well above the 100 t floor
        _row(scope=1, sub_scope="comb", codice_sito="B", anno=2024, tco2e="750"),
    ]
    res = reconcile(snapshot_emissions=prior, current_emissions=curr)
    # Aggregate delta is (10850-10500)/10500 ~ 3.33% (below 5%)
    assert res.total_delta_pct is not None
    assert abs(res.total_delta_pct) < Decimal("5")
    # But one row exceeds 2 * 5% = 10% AND its abs_delta >= 100, so restatement
    # is required by the per-row gate.
    assert res.restatement_required is True


# ---------------------------------------------------------------------------
# 8. Both sets empty -> no rows, restatement False, totals zero.
# ---------------------------------------------------------------------------
def test_empty_sets_produce_empty_result() -> None:
    res = reconcile(snapshot_emissions=[], current_emissions=[])
    assert res.total_prior == Decimal("0")
    assert res.total_current == Decimal("0")
    assert res.total_abs_delta == Decimal("0")
    assert res.total_delta_pct is None
    assert res.rows == ()
    assert res.material_count == 0
    assert res.restatement_required is False


# ---------------------------------------------------------------------------
# Bonus: methodology annotation channel overrides factor-version heuristic.
# ---------------------------------------------------------------------------
def test_methodology_flag_overrides() -> None:
    prior = [
        _row(scope=1, sub_scope="comb", codice_sito="A", anno=2024, tco2e="100",
             factor_version="v1"),
    ]
    curr = [
        _row(scope=1, sub_scope="comb", codice_sito="A", anno=2024, tco2e="110",
             factor_version="v1"),
    ]
    res = reconcile(
        snapshot_emissions=prior,
        current_emissions=curr,
        methodology_flags=[(1, "comb", "A", 2024)],
    )
    assert res.rows[0].cause_category == "methodology"

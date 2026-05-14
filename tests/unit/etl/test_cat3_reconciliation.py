"""Unit tests for Cat 3 FR-11 reconciliation logic.

Tests that:
- Delta = 0 on data matching the actual CSVs (Phase 3 verified)
- Non-zero delta produces a WARN finding
- INFO finding is always logged regardless of delta value
"""

from __future__ import annotations

import pandas as pd

from ghg_tool.etl.cat3_reconciliation import compute_cat3_reconciliation


def _make_s1_df(gas_nat_2024: float, gasolio_2024: float) -> pd.DataFrame:
    """Minimal Scope 1 DataFrame for 2024.

    Uses a single IANO row per fuel so that Σ Scope 1 == the passed argument,
    making delta arithmetic transparent in the reconciliation tests.
    """
    return pd.DataFrame(
        {
            "Anno": ["2024", "2024"],
            "Codice_Sito": ["IANO", "IANO"],
            "Combustibile": ["GAS_NAT", "GASOLIO"],
            "Quantità": [str(gas_nat_2024), str(gasolio_2024)],
        }
    )


def _make_s3_df(gas_nat_qty: float, gasolio_qty: float) -> pd.DataFrame:
    """Minimal Scope 3 Cat 3 rows with WTT subcategories."""
    return pd.DataFrame(
        {
            "Scope": ["3", "3"],
            "Anno": ["2024", "2024"],
            "Categoria_S3": ["3", "3"],
            "Sottocategoria": ["WTT Gas Naturale", "WTT Gasolio"],
            "Metodo": ["activity-based", "activity-based"],
            "Combustibile": ["GAS_NAT", "GASOLIO"],
            "Quantità": [str(gas_nat_qty), str(gasolio_qty)],
            "Unità": ["Sm3", "litri"],
            "Fonte_Dato": ["Derivato da Scope 1/2 per FR-11"] * 2,
            "Qualità_Dato": ["D"] * 2,
            "Stato_Dato": ["Definitivo"] * 2,
        }
    )


class TestCat3Reconciliation:

    def test_zero_delta_produces_info_finding_only(self) -> None:
        """Phase 3 confirmed: current data delta = 0 — only INFO findings expected."""
        s1_gas_sum = 22916841 + 4569554 + 0 + 2738 + 15211 + 10632 + 5634446
        df_s1 = _make_s1_df(gas_nat_2024=s1_gas_sum, gasolio_2024=341268)
        df_s3 = _make_s3_df(gas_nat_qty=float(s1_gas_sum), gasolio_qty=341268.0)
        findings = compute_cat3_reconciliation(df_s1, df_s3)
        rule_ids = [f["rule_id"] for f in findings]
        assert "FR-11-CAT3-RECONCIL" in rule_ids
        # No WARN delta finding expected when delta = 0
        assert "DQ-WARN-CAT3-DELTA" not in rule_ids

    def test_info_finding_always_logged(self) -> None:
        """INFO finding must be logged regardless of delta value."""
        df_s1 = _make_s1_df(gas_nat_2024=33149422, gasolio_2024=341268)
        df_s3 = _make_s3_df(gas_nat_qty=33149422.0, gasolio_qty=341268.0)
        findings = compute_cat3_reconciliation(df_s1, df_s3)
        info_findings = [f for f in findings if f["rule_id"] == "FR-11-CAT3-RECONCIL"]
        assert len(info_findings) >= 1, "INFO finding must always be logged"

    def test_nonzero_delta_produces_warn_finding(self) -> None:
        """Non-zero delta between Cat3 CSV and Σ Scope 1 must produce DQ-WARN."""
        s1_gas_sum = 22916841 + 4569554 + 0 + 2738 + 15211 + 10632 + 5634446
        cat3_inflated = s1_gas_sum * 1.18  # +18% simulated discrepancy
        df_s1 = _make_s1_df(gas_nat_2024=s1_gas_sum, gasolio_2024=341268)
        df_s3 = _make_s3_df(gas_nat_qty=cat3_inflated, gasolio_qty=341268.0)
        findings = compute_cat3_reconciliation(df_s1, df_s3)
        warn_findings = [f for f in findings if f["rule_id"] == "DQ-WARN-CAT3-DELTA"]
        assert len(warn_findings) >= 1, "Non-zero delta must produce WARN finding"
        # Delta finding must not block pipeline
        for f in warn_findings:
            assert f["blocks_pipeline"] is False

    def test_correct_delta_value_in_finding(self) -> None:
        """Finding value_observed (delta) must equal cat3_qty - sigma_scope1."""
        s1_gas_sum = 28149392.0  # sigma scope 1
        cat3_gas = 33149422.0    # CSV Cat 3 (simulated inflated value)
        expected_delta = cat3_gas - s1_gas_sum
        df_s1 = _make_s1_df(gas_nat_2024=s1_gas_sum, gasolio_2024=341268)
        df_s3 = _make_s3_df(gas_nat_qty=cat3_gas, gasolio_qty=341268.0)
        findings = compute_cat3_reconciliation(df_s1, df_s3)
        warn = next(
            (f for f in findings if f["rule_id"] == "DQ-WARN-CAT3-DELTA"
             and "GAS_NAT" in f.get("metric", "")),
            None
        )
        assert warn is not None
        assert abs(warn["value_observed"] - expected_delta) < 1.0

"""Unit tests for DQ gate check functions.

Tests all DQ-CRIT (01..05) and DQ-WARN (01, 02) gates.
No database access.
"""

from __future__ import annotations

import pandas as pd

from ghg_tool.etl.dq_gates.checks import (
    check_facility_coverage,
    check_mandatory_columns,
    check_negative_quantities,
    check_outlier_zscore,
    check_temporal_gap,
    check_warn_01_viano_electricity,
    check_warn_02_estimated_quality,
)

# ---------------------------------------------------------------------------
# DQ-CRIT-01: Facility coverage
# ---------------------------------------------------------------------------

class TestDQCrit01FacilityCoverage:

    def test_passes_when_all_7_sites_present(self) -> None:
        siti = ["IANO", "VIANO", "VIANO_GARGOLA", "CASALGRANDE",
                "FIORANO", "SASSUOLO", "FRASSINORO"]
        df_s1 = pd.DataFrame({
            "Anno": ["2024"] * 7,
            "Codice_Sito": siti,
            "Combustibile": ["GAS_NAT"] * 7,
            "Quantità": ["100"] * 7,
        })
        df_s2 = pd.DataFrame({
            "Anno": ["2024"] * 7,
            "Codice_Sito": siti,
            "Voce_S2": ["EE_Acquistata_GO"] * 7,
            "Quantità": ["1000"] * 7,
        })
        passes, findings = check_facility_coverage(df_s1, df_s2)
        assert passes is True
        assert findings == []

    def test_fails_when_site_missing(self) -> None:
        # Only 6 sites — VIANO_GARGOLA missing
        siti = ["IANO", "VIANO", "CASALGRANDE", "FIORANO", "SASSUOLO", "FRASSINORO"]
        df_s1 = pd.DataFrame({
            "Anno": ["2024"] * 6,
            "Codice_Sito": siti,
            "Combustibile": ["GAS_NAT"] * 6,
            "Quantità": ["100"] * 6,
        })
        df_s2 = pd.DataFrame(columns=["Anno", "Codice_Sito", "Voce_S2", "Quantità"])
        passes, findings = check_facility_coverage(df_s1, df_s2)
        assert passes is False
        assert any(f["rule_id"] == "DQ-CRIT-01" for f in findings)
        assert any(f["blocks_pipeline"] for f in findings)


# ---------------------------------------------------------------------------
# DQ-CRIT-02: Mandatory columns
# ---------------------------------------------------------------------------

class TestDQCrit02MandatoryColumns:

    def test_passes_with_complete_data(self) -> None:
        df = pd.DataFrame({
            "Anno": ["2024"],
            "Codice_Sito": ["IANO"],
            "Combustibile": ["GAS_NAT"],
            "Quantità": ["100"],
            "Unità": ["Sm3"],
        })
        passes, findings = check_mandatory_columns(df, 1)
        assert passes is True

    def test_fails_with_null_quantita(self) -> None:
        df = pd.DataFrame({
            "Anno": ["2024"],
            "Codice_Sito": ["IANO"],
            "Combustibile": ["GAS_NAT"],
            "Quantità": [None],
            "Unità": ["Sm3"],
        })
        passes, findings = check_mandatory_columns(df, 1)
        assert passes is False
        assert any(f["rule_id"] == "DQ-CRIT-02" for f in findings)
        assert any(f["blocks_pipeline"] for f in findings)

    def test_fails_with_empty_string_codice_sito(self) -> None:
        df = pd.DataFrame({
            "Anno": ["2024"],
            "Codice_Sito": [""],
            "Combustibile": ["GAS_NAT"],
            "Quantità": ["100"],
            "Unità": ["Sm3"],
        })
        passes, findings = check_mandatory_columns(df, 1)
        assert passes is False


# ---------------------------------------------------------------------------
# DQ-CRIT-03: Negative quantities
# ---------------------------------------------------------------------------

class TestDQCrit03NegativeQuantity:

    def test_passes_with_non_negative_values(self) -> None:
        df = pd.DataFrame({
            "Anno": ["2024", "2024"],
            "Codice_Sito": ["IANO", "VIANO"],
            "Quantità": ["100", "0"],
        })
        passes, findings = check_negative_quantities(df, 1)
        assert passes is True
        assert findings == []

    def test_fails_with_negative_value(self) -> None:
        df = pd.DataFrame({
            "Anno": ["2024"],
            "Codice_Sito": ["IANO"],
            "Quantità": ["-5"],
        })
        passes, findings = check_negative_quantities(df, 1)
        assert passes is False
        assert any(f["rule_id"] == "DQ-CRIT-03" for f in findings)
        assert any(f["blocks_pipeline"] for f in findings)

    def test_zero_is_allowed(self) -> None:
        df = pd.DataFrame({
            "Anno": ["2024"],
            "Codice_Sito": ["VIANO_GARGOLA"],
            "Quantità": ["0"],
        })
        passes, _ = check_negative_quantities(df, 1)
        assert passes is True


# ---------------------------------------------------------------------------
# DQ-CRIT-04: Z-score outlier
# ---------------------------------------------------------------------------

class TestDQCrit04ZScore:

    def test_flags_extreme_outlier(self) -> None:
        # Synthetic scenario: 6 sites at ~1 000 000 Sm3, VIANO_GARGOLA = 11 Sm3.
        # With n=7 the max achievable z-score is (n-1)/sqrt(n) ≈ 2.27.
        # Using threshold 2.0 and near-equal cluster, VIANO_GARGOLA's |z| ≈ 2.27.
        df = pd.DataFrame({
            "Anno": ["2025"] * 7,
            "Codice_Sito": ["IANO", "VIANO", "VIANO_GARGOLA", "CASALGRANDE",
                            "FIORANO", "SASSUOLO", "FRASSINORO"],
            "Combustibile": ["GAS_NAT"] * 7,
            "Quantità": ["1000000", "1000000", "11", "1000000",
                         "1000000", "1000000", "1000000"],
        })
        passes, findings = check_outlier_zscore(df, 1)
        # VIANO_GARGOLA's z-score ≈ 2.27 > 2.0 threshold
        assert any(f["rule_id"] == "DQ-CRIT-04" for f in findings)

    def test_passes_with_normal_distribution(self) -> None:
        # Synthetic normal-ish data — all values within 2 SD
        df = pd.DataFrame({
            "Anno": ["2024"] * 5,
            "Codice_Sito": [f"SITE_{i}" for i in range(5)],
            "Combustibile": ["GAS_NAT"] * 5,
            "Quantità": ["1000", "1050", "980", "1020", "970"],
        })
        passes, findings = check_outlier_zscore(df, 1)
        assert passes is True
        assert findings == []


# ---------------------------------------------------------------------------
# DQ-CRIT-05: Temporal gap
# ---------------------------------------------------------------------------

class TestDQCrit05TemporalGap:

    def test_no_gap_when_all_sites_both_years(self) -> None:
        siti = ["IANO", "VIANO", "VIANO_GARGOLA", "CASALGRANDE",
                "FIORANO", "SASSUOLO", "FRASSINORO"]
        rows = []
        for yr in ["2024", "2025"]:
            for s in siti:
                rows.append({"Anno": yr, "Codice_Sito": s, "Combustibile": "GAS_NAT",
                              "Quantità": "100"})
        df_s1 = pd.DataFrame(rows)
        df_s2 = pd.DataFrame(columns=["Anno", "Codice_Sito", "Voce_S2", "Quantità"])
        passes, findings = check_temporal_gap(df_s1, df_s2)
        assert passes is True
        assert findings == []

    def test_detects_temporal_gap(self) -> None:
        # VIANO_GARGOLA only in 2025, not 2024, without explicit zero
        rows = [
            {"Anno": "2024", "Codice_Sito": "IANO", "Combustibile": "GAS_NAT", "Quantità": "100"},
            {"Anno": "2025", "Codice_Sito": "IANO", "Combustibile": "GAS_NAT", "Quantità": "100"},
            {"Anno": "2025", "Codice_Sito": "VIANO_GARGOLA", "Combustibile": "GAS_NAT",
             "Quantità": "11"},
        ]
        df_s1 = pd.DataFrame(rows)
        df_s2 = pd.DataFrame(columns=["Anno", "Codice_Sito", "Voce_S2", "Quantità"])
        passes, findings = check_temporal_gap(df_s1, df_s2)
        assert passes is False
        assert any(f["rule_id"] == "DQ-CRIT-05" for f in findings)


# ---------------------------------------------------------------------------
# DQ-WARN-01: VIANO electricity ratio
# ---------------------------------------------------------------------------

class TestDQWarn01VianoElectricity:

    def test_fires_when_ratio_below_threshold(self) -> None:
        df_s2 = pd.DataFrame({
            "Codice_Sito": ["VIANO", "VIANO"],
            "Anno": ["2024", "2025"],
            "Voce_S2": ["EE_Acquistata_GO", "EE_Acquistata_GO"],
            "Quantità": ["6551604", "3268364"],
        })
        passes, findings = check_warn_01_viano_electricity(df_s2)
        assert passes is True  # WARN does not block
        assert any(f["rule_id"] == "DQ-WARN-01" for f in findings)
        warn = next(f for f in findings if f["rule_id"] == "DQ-WARN-01")
        assert warn["severity"] == "WARN"
        assert warn["blocks_pipeline"] is False

    def test_does_not_fire_when_ratio_normal(self) -> None:
        df_s2 = pd.DataFrame({
            "Codice_Sito": ["VIANO", "VIANO"],
            "Anno": ["2024", "2025"],
            "Voce_S2": ["EE_Acquistata_GO", "EE_Acquistata_GO"],
            "Quantità": ["1000000", "900000"],  # ratio 0.9 — above 0.6 threshold
        })
        passes, findings = check_warn_01_viano_electricity(df_s2)
        assert passes is True
        assert findings == []


# ---------------------------------------------------------------------------
# DQ-WARN-02: Estimated quality code
# ---------------------------------------------------------------------------

class TestDQWarn02EstimatedQuality:

    def test_fires_for_estimated_rows(self) -> None:
        df = pd.DataFrame({
            "Anno": ["2024", "2024"],
            "Codice_Sito": ["IANO", "VIANO"],
            "Qualità_Dato": ["E", "P"],
        })
        passes, findings = check_warn_02_estimated_quality(df, 1)
        assert passes is True  # WARN does not block
        assert len(findings) == 1
        assert findings[0]["rule_id"] == "DQ-WARN-02"
        assert findings[0]["codice_sito"] == "IANO"

    def test_does_not_fire_for_primary_quality(self) -> None:
        df = pd.DataFrame({
            "Anno": ["2024"],
            "Codice_Sito": ["IANO"],
            "Qualità_Dato": ["P"],
        })
        passes, findings = check_warn_02_estimated_quality(df, 1)
        assert passes is True
        assert findings == []

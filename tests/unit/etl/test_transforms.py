"""Unit tests for ETL transform functions (FR-01, FR-02, FR-37).

No database access.  Pure pandas DataFrame manipulation.
"""

from __future__ import annotations

import pandas as pd

from ghg_tool.etl.transforms.synth_rows import (
    _FR37_FONTE,
    _FR37_QUALITA,
    _FR37_STATO,
    apply_fr37_cat3_metadata_defaulting,
    synthesise_sassuolo_grid_2025,
    synthesise_viano_gargola_gas_nat_2024,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_scope1_df() -> pd.DataFrame:
    """Minimal Scope 1 DataFrame without VIANO_GARGOLA GAS_NAT 2024."""
    return pd.DataFrame(
        {
            "Scope": ["1"] * 6,
            "Anno": ["2024"] * 6,
            "Codice_Sito": ["IANO", "VIANO", "CASALGRANDE", "FIORANO", "SASSUOLO", "FRASSINORO"],
            "Categoria_S1": ["Combustione stazionaria"] * 6,
            "Combustibile": ["GAS_NAT"] * 6,
            "Quantità": ["22916841", "4569554", "2738", "15211", "10632", "5634446"],
            "Unità": ["Sm3"] * 6,
            "Fonte_Dato": ["Contatore"] * 6,
            "Qualità_Dato": ["P"] * 6,
            "Stato_Dato": ["Definitivo"] * 6,
            "Note": [None] * 6,
        }
    )


def _base_scope2_df() -> pd.DataFrame:
    """Minimal Scope 2 DataFrame without SASSUOLO Grid 2025."""
    return pd.DataFrame(
        {
            "Scope": ["2"] * 7,
            "Anno": ["2024"] * 7,
            "Codice_Sito": ["IANO", "VIANO", "VIANO_GARGOLA", "CASALGRANDE",
                            "FIORANO", "SASSUOLO", "FRASSINORO"],
            "Voce_S2": ["EE_Acquistata_GO"] * 7,
            "Quantità": ["3193698", "6551604", "159518", "358307", "344808", "377358", "8716707"],
            "Unità": ["kWh"] * 7,
            "Strumento_MB": ["GO_GSE"] * 7,
            "Fonte_Dato": ["Fattura"] * 7,
            "Qualità_Dato": ["P"] * 7,
            "Stato_Dato": ["Definitivo"] * 7,
            "Note": [None] * 7,
        }
    )


def _base_scope3_df_with_blank_cat3() -> pd.DataFrame:
    """Scope 3 DataFrame with 2 Cat 3 WTT rows with blank metadata."""
    return pd.DataFrame(
        {
            "Scope": ["3"] * 4,
            "Anno": ["2024", "2024", "2024", "2024"],
            "Categoria_S3": ["1", "1", "3", "3"],
            "Sottocategoria": ["Argille", "Feldspati", "WTT Gas Naturale", "WTT Gasolio"],
            "Metodo": ["mass-based", "mass-based", "activity-based", "activity-based"],
            "Combustibile": [None, None, "GAS_NAT", "GASOLIO"],
            "Quantità": ["5000", "3000", "33149422", "341268"],
            "Unità": ["t", "t", "Sm3", "litri"],
            "Fonte_Dato": ["Dichiarazione", "Dichiarazione", "", ""],
            "Qualità_Dato": ["P", "P", "", ""],
            "Stato_Dato": ["Definitivo", "Definitivo", "", ""],
            "Note": [None, None, None, None],
        }
    )


# ---------------------------------------------------------------------------
# FR-01 tests
# ---------------------------------------------------------------------------

class TestFR01VGGasNatSynth:
    """Tests for FR-01: VIANO_GARGOLA GAS_NAT 2024 synthesised zero row."""

    def test_adds_zero_row_when_absent(self) -> None:
        df = _base_scope1_df()
        result_df, findings = synthesise_viano_gargola_gas_nat_2024(df)
        assert len(result_df) == len(df) + 1, "Should have added exactly 1 row"

    def test_synthesised_row_has_correct_values(self) -> None:
        df = _base_scope1_df()
        result_df, _ = synthesise_viano_gargola_gas_nat_2024(df)
        vg_row = result_df[
            (result_df["Codice_Sito"] == "VIANO_GARGOLA")
            & (result_df["Anno"] == "2024")
            & (result_df["Combustibile"] == "GAS_NAT")
        ]
        assert len(vg_row) == 1, "Exactly one VIANO_GARGOLA GAS_NAT 2024 row expected"
        assert vg_row.iloc[0]["Quantità"] == "0", "Quantità must be 0"
        assert vg_row.iloc[0]["_provenance"] == "auto_zero_user_confirmed"

    def test_produces_info_finding(self) -> None:
        df = _base_scope1_df()
        _, findings = synthesise_viano_gargola_gas_nat_2024(df)
        assert len(findings) == 1
        assert findings[0]["rule_id"] == "FR-01-SYNTH"
        assert findings[0]["severity"] == "INFO"
        assert findings[0]["codice_sito"] == "VIANO_GARGOLA"
        assert findings[0]["anno"] == 2024

    def test_idempotent_does_not_duplicate(self) -> None:
        df = _base_scope1_df()
        df_once, _ = synthesise_viano_gargola_gas_nat_2024(df)
        df_twice, findings = synthesise_viano_gargola_gas_nat_2024(df_once)
        vg_rows = df_twice[
            (df_twice["Codice_Sito"] == "VIANO_GARGOLA")
            & (df_twice["Anno"].astype(str) == "2024")
            & (df_twice["Combustibile"] == "GAS_NAT")
        ]
        assert len(vg_rows) == 1, "Idempotent: must not add a second row"
        assert findings == [], "No findings on second run (already present)"


# ---------------------------------------------------------------------------
# FR-02 tests
# ---------------------------------------------------------------------------

class TestFR02SassuoloGridSynth:
    """Tests for FR-02: SASSUOLO EE_Acquistata_Grid 2025 = 0 kWh."""

    def test_adds_zero_row_when_absent(self) -> None:
        df = _base_scope2_df()
        result_df, findings = synthesise_sassuolo_grid_2025(df)
        assert len(result_df) == len(df) + 1

    def test_synthesised_row_has_correct_values(self) -> None:
        df = _base_scope2_df()
        result_df, _ = synthesise_sassuolo_grid_2025(df)
        row = result_df[
            (result_df["Codice_Sito"] == "SASSUOLO")
            & (result_df["Anno"].astype(str) == "2025")
            & (result_df["Voce_S2"] == "EE_Acquistata_Grid")
        ]
        assert len(row) == 1
        assert row.iloc[0]["Quantità"] == "0"
        assert row.iloc[0]["_provenance"] == "auto_zero_user_confirmed"

    def test_produces_info_finding(self) -> None:
        df = _base_scope2_df()
        _, findings = synthesise_sassuolo_grid_2025(df)
        assert len(findings) == 1
        assert findings[0]["rule_id"] == "FR-02-SYNTH"
        assert findings[0]["severity"] == "INFO"
        assert findings[0]["codice_sito"] == "SASSUOLO"
        assert findings[0]["anno"] == 2025

    def test_idempotent(self) -> None:
        df = _base_scope2_df()
        df_once, _ = synthesise_sassuolo_grid_2025(df)
        df_twice, findings = synthesise_sassuolo_grid_2025(df_once)
        rows = df_twice[
            (df_twice["Codice_Sito"] == "SASSUOLO")
            & (df_twice["Anno"].astype(str) == "2025")
            & (df_twice["Voce_S2"] == "EE_Acquistata_Grid")
        ]
        assert len(rows) == 1
        assert findings == []


# ---------------------------------------------------------------------------
# FR-37 tests
# ---------------------------------------------------------------------------

class TestFR37Cat3MetadataDefaulting:
    """Tests for FR-37: Cat 3 WTT/T&D metadata defaulting."""

    def test_defaults_applied_to_blank_cat3_rows(self) -> None:
        df = _base_scope3_df_with_blank_cat3()
        result_df, findings = apply_fr37_cat3_metadata_defaulting(df)
        defaulted = result_df[result_df["_metadata_defaulted"] == True]  # noqa: E712
        assert len(defaulted) >= 2, "At least 2 rows should have been defaulted"

    def test_default_values_correct(self) -> None:
        df = _base_scope3_df_with_blank_cat3()
        result_df, _ = apply_fr37_cat3_metadata_defaulting(df)
        for _, row in result_df[result_df["_metadata_defaulted"] == True].iterrows():  # noqa: E712
            assert row["Fonte_Dato"] == _FR37_FONTE
            assert row["Qualità_Dato"] == _FR37_QUALITA
            assert row["Stato_Dato"] == _FR37_STATO
            assert row["_defaulting_rule_id"] == "FR-37-DEFAULT"

    def test_non_cat3_rows_not_defaulted(self) -> None:
        df = _base_scope3_df_with_blank_cat3()
        result_df, _ = apply_fr37_cat3_metadata_defaulting(df)
        not_defaulted = result_df[result_df["_metadata_defaulted"] == False]  # noqa: E712
        # Cat 1 rows should not be touched
        cat1_rows = not_defaulted[not_defaulted["Categoria_S3"] == "1"]
        assert len(cat1_rows) == 2

    def test_produces_info_finding_per_defaulted_row(self) -> None:
        df = _base_scope3_df_with_blank_cat3()
        _, findings = apply_fr37_cat3_metadata_defaulting(df)
        info_findings = [f for f in findings if f["rule_id"] == "FR-37-DEFAULT"]
        assert len(info_findings) >= 2
        for f in info_findings:
            assert f["severity"] == "INFO"

    def test_idempotent_no_double_default(self) -> None:
        df = _base_scope3_df_with_blank_cat3()
        df_once, _ = apply_fr37_cat3_metadata_defaulting(df)
        df_twice, findings_second = apply_fr37_cat3_metadata_defaulting(df_once)
        assert len(findings_second) == 0, "No findings on second run — already defaulted"

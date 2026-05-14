"""ETL transform functions for synthesised rows and metadata defaulting.

All transforms are pure functions (df → df) with a sidecar list of
DQFinding-like dicts for audit logging.  They do not touch the database.

Transforms implemented here:
  - FR-01: VIANO_GARGOLA GAS_NAT 2024 = 0 Sm³ (auto_zero_user_confirmed)
  - FR-02: SASSUOLO EE_Acquistata_Grid 2025 = 0 kWh (auto_zero_user_confirmed)
  - FR-37: Cat 3 WTT/T&D metadata defaulting for 10 blank rows
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Type alias for a lightweight finding dict (becomes DqFinding in DB via writer)
FindingDict = dict[str, Any]

# FR-37 default values per requirements.md §11 DQ-CRIT-02 resolution
_FR37_FONTE = "Derivato da Scope 1/2 per FR-11"
_FR37_QUALITA = "D"
_FR37_STATO = "Definitivo"
_FR37_RULE_ID = "FR-37-DEFAULT"

# Cat 3 subcategories that receive FR-37 defaulting (WTT and T&D rows)
_CAT3_WTT_TND_SUBS = {
    "WTT Gas Naturale",
    "WTT Gasolio",
    "WTT Benzina",
    "WTT Elettricità (generazione)",
    "WTT Elettricità",
    "T&D Losses Elettricità",
    "T&D Losses",
}


def synthesise_viano_gargola_gas_nat_2024(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[FindingDict]]:
    """FR-01: Synthesise VIANO_GARGOLA GAS_NAT 2024 = 0 Sm³ zero row.

    The native CSV contains no row for VIANO_GARGOLA GAS_NAT in 2024 because
    the gas connection was not active.  Without this synthesised row,
    DQ-CRIT-01 (facility coverage < 7/7) and DQ-CRIT-05 (temporal gap) fire.

    Idempotent: if the synthesised row already exists in ``df``, it is not
    duplicated.

    Args:
        df: Raw Scope 1 DataFrame from ``csv_reader.read_scope1()``.

    Returns:
        Tuple of (transformed DataFrame, list of INFO findings for audit log).
    """
    findings: list[FindingDict] = []
    mask = (
        (df["Codice_Sito"] == "VIANO_GARGOLA")
        & (df["Anno"].astype(str) == "2024")
        & (df["Combustibile"] == "GAS_NAT")
    )
    if mask.any():
        # Already present — idempotent guard
        return df, findings

    synth_row: dict[str, Any] = {
        "Scope": "1",
        "Anno": "2024",
        "Codice_Sito": "VIANO_GARGOLA",
        "Categoria_S1": "Combustione stazionaria",
        "Combustibile": "GAS_NAT",
        "Quantità": "0",
        "Unità": "Sm3",
        "Fonte_Dato": "auto_zero_user_confirmed",
        "Qualità_Dato": "P",
        "Stato_Dato": "Definitivo",
        "Note": "VIANO_GARGOLA — no gas connection in 2024 (user confirmed 2026-05-13). "
                "ETL synthesised zero row; DQ-CRIT-01/04/05 closed.",
        "_provenance": "auto_zero_user_confirmed",
        "_provenance_rationale": "No gas connection 2024 — user confirmed 2026-05-13",
    }
    df = pd.concat([df, pd.DataFrame([synth_row])], ignore_index=True)
    findings.append(
        {
            "rule_id": "FR-01-SYNTH",
            "severity": "INFO",
            "scope": 1,
            "codice_sito": "VIANO_GARGOLA",
            "anno": 2024,
            "trigger_desc": "ETL synthesised VIANO_GARGOLA GAS_NAT 2024 = 0 Sm3 "
                            "(auto_zero_user_confirmed per FR-01; user confirmation 2026-05-13).",
        }
    )
    return df, findings


def synthesise_sassuolo_grid_2025(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[FindingDict]]:
    """FR-02: Synthesise SASSUOLO EE_Acquistata_Grid 2025 = 0 kWh zero row.

    User confirmed on 2026-05-13 that SASSUOLO switched to 100% GO contract
    in 2025.  Without the explicit zero row, DQ-CRIT-05 (temporal gap) fires.

    Idempotent: if the synthesised row already exists in ``df``, it is not
    duplicated.

    Args:
        df: Raw Scope 2 DataFrame from ``csv_reader.read_scope2()``.

    Returns:
        Tuple of (transformed DataFrame, list of INFO findings for audit log).
    """
    findings: list[FindingDict] = []
    mask = (
        (df["Codice_Sito"] == "SASSUOLO")
        & (df["Anno"].astype(str) == "2025")
        & (df["Voce_S2"] == "EE_Acquistata_Grid")
    )
    if mask.any():
        return df, findings

    synth_row: dict[str, Any] = {
        "Scope": "2",
        "Anno": "2025",
        "Codice_Sito": "SASSUOLO",
        "Voce_S2": "EE_Acquistata_Grid",
        "Quantità": "0",
        "Unità": "kWh",
        "Strumento_MB": "Grid_Residual",
        "Fonte_Dato": "auto_zero_user_confirmed",
        "Qualità_Dato": "P",
        "Stato_Dato": "Definitivo",
        "Note": "SASSUOLO 100% GO contract in 2025 — user confirmed 2026-05-13. "
                "Grid = 0 kWh explicitly. DQ-WARN-05 RESOLVED.",
        "_provenance": "auto_zero_user_confirmed",
        "_provenance_rationale": "100% GO contract switch confirmed user 2026-05-13",
    }
    df = pd.concat([df, pd.DataFrame([synth_row])], ignore_index=True)
    findings.append(
        {
            "rule_id": "FR-02-SYNTH",
            "severity": "INFO",
            "scope": 2,
            "codice_sito": "SASSUOLO",
            "anno": 2025,
            "trigger_desc": "ETL synthesised SASSUOLO EE_Acquistata_Grid 2025 = 0 kWh "
                            "(auto_zero_user_confirmed; DQ-WARN-05 RESOLVED).",
        }
    )
    return df, findings


def apply_fr37_cat3_metadata_defaulting(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[FindingDict]]:
    """FR-37: Apply default metadata to Cat 3 WTT/T&D rows with blank fields.

    The 10 Cat 3 WTT/T&D rows in scope3_categorie.csv have blank
    Fonte_Dato, Qualità_Dato, Stato_Dato.  FR-37 mandates deterministic
    defaults at ingestion time:
      - Fonte_Dato = "Derivato da Scope 1/2 per FR-11"
      - Qualità_Dato = "D"
      - Stato_Dato = "Definitivo"

    The native CSV is NOT modified.  Defaulting is a runtime transform only.
    Each defaulted row generates one INFO-level DQ finding (rule_id='FR-37-DEFAULT').

    Idempotent: already-defaulted rows (non-blank metadata) are not re-defaulted.

    Args:
        df: Raw Scope 3 DataFrame from ``csv_reader.read_scope3()``.

    Returns:
        Tuple of (transformed DataFrame with defaults applied, INFO findings list).
    """
    findings: list[FindingDict] = []
    df = df.copy()

    # Add tracking columns if not present
    if "_metadata_defaulted" not in df.columns:
        df["_metadata_defaulted"] = False
        df["_defaulting_rule_id"] = pd.NA

    # FR-37 defaults ("Derivato da Scope 1/2 per FR-11") are only valid for
    # the WTT and T&D Losses subcategories — applying them to other Cat 3
    # rows (e.g. Cat 5 waste, Cat 1 purchased goods) would falsify the
    # provenance audit trail.  Restrict the mask to the whitelist only.
    cat3_mask = df["Sottocategoria"].str.strip().isin(_CAT3_WTT_TND_SUBS)
    blank_mask = cat3_mask & (
        df["Fonte_Dato"].str.strip().eq("") | df["Fonte_Dato"].isna()
    )

    for idx in df[blank_mask].index:
        row = df.loc[idx]
        df.at[idx, "Fonte_Dato"] = _FR37_FONTE
        df.at[idx, "Qualità_Dato"] = _FR37_QUALITA
        df.at[idx, "Stato_Dato"] = _FR37_STATO
        df.at[idx, "_metadata_defaulted"] = True
        df.at[idx, "_defaulting_rule_id"] = _FR37_RULE_ID
        findings.append(
            {
                "rule_id": _FR37_RULE_ID,
                "severity": "INFO",
                "scope": 3,
                "codice_sito": None,
                "anno": int(row["Anno"]) if pd.notna(row.get("Anno")) else None,
                "metric": f"Sottocategoria={row.get('Sottocategoria', '')}",
                "trigger_desc": (
                    f"FR-37 metadata defaulted for Cat 3 WTT/T&D row: "
                    f"Sottocategoria={row.get('Sottocategoria', '')!r}, "
                    f"Anno={row.get('Anno', '')}. "
                    f"Set Fonte_Dato={_FR37_FONTE!r}, "
                    f"Qualità_Dato={_FR37_QUALITA!r}, Stato_Dato={_FR37_STATO!r}."
                ),
            }
        )
    return df, findings

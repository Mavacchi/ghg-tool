"""Scope 3 Cat 3 reconciliation — FR-11 Σ Scope 1 vs CSV Cat 3 Quantità.

Per requirements.md FR-11:
  WTT calculations use Σ Scope 1 fuel quantities as the source of truth.
  The Cat 3 CSV Quantità is retained for audit transparency only.
  The delta (CSV − Σ Scope 1) is logged to dq_findings regardless of value.

Phase 3 verification confirmed current data delta = 0 across all
fuel/year combinations (the +18% delta in v1.1.0 was a requirements-agent
arithmetic error, not a real discrepancy).

This module computes the delta and returns DQ findings to be persisted by
the orchestrator.  It does NOT compute emissions — that is the data-analyst's
job in wave 2.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

FindingDict = dict[str, Any]

# Cat 3 subcategory → Scope 1 Combustibile mapping
_CAT3_FUEL_MAP = {
    "WTT Gas Naturale": "GAS_NAT",
    "WTT Gasolio": "GASOLIO",
    "WTT Benzina": "BENZINA",
}


def compute_cat3_reconciliation(
    df_s1: pd.DataFrame,
    df_s3: pd.DataFrame,
) -> list[FindingDict]:
    """Compute delta between Cat 3 CSV Quantità and Σ Scope 1 fuel consumption.

    For each (Combustibile, Anno) pair found in the Cat 3 WTT rows, computes:
      - sigma_scope1: sum of Scope 1 Quantità for that fuel and year across all sites
      - cat3_qty: Cat 3 CSV Quantità for the corresponding WTT row
      - delta = cat3_qty - sigma_scope1

    A DQ finding (INFO level, blocks_pipeline=False) is logged regardless of
    the delta value.  If delta != 0 a WARN finding is also emitted.

    Args:
        df_s1: Validated Scope 1 DataFrame (post-synthesis, numeric Quantità).
        df_s3: Validated Scope 3 DataFrame (post-FR-37, numeric Quantità).

    Returns:
        List of FindingDict entries to be written to dq_findings table.
    """
    findings: list[FindingDict] = []
    s1_qty = pd.to_numeric(df_s1["Quantità"], errors="coerce")
    df_s1 = df_s1.copy()
    df_s1["_qty"] = s1_qty

    s3_qty = pd.to_numeric(df_s3["Quantità"], errors="coerce")
    df_s3 = df_s3.copy()
    df_s3["_qty"] = s3_qty

    for sub_cat, combustibile in _CAT3_FUEL_MAP.items():
        cat3_rows = df_s3[
            df_s3["Sottocategoria"].str.strip().str.lower() == sub_cat.lower()
        ]
        if cat3_rows.empty:
            continue

        for _, cat3_row in cat3_rows.iterrows():
            anno = int(cat3_row["Anno"])
            cat3_val = float(cat3_row["_qty"]) if pd.notna(cat3_row["_qty"]) else 0.0

            s1_subset = df_s1[
                (df_s1["Combustibile"] == combustibile)
                & (df_s1["Anno"].astype(str) == str(anno))
            ]
            sigma_s1 = float(s1_subset["_qty"].sum())
            delta = cat3_val - sigma_s1

            findings.append(
                {
                    "rule_id": "FR-11-CAT3-RECONCIL",
                    "severity": "INFO",
                    "scope": 3,
                    "anno": anno,
                    "codice_sito": None,
                    "metric": f"cat3_delta_{combustibile}_{anno}",
                    "value_observed": cat3_val,
                    "value_reference": sigma_s1,
                    "trigger_desc": (
                        f"FR-11 Cat 3 reconciliation: Sottocategoria={sub_cat!r}, "
                        f"Anno={anno}, Cat3_CSV_Quantità={cat3_val}, "
                        f"Σ_Scope1_{combustibile}={sigma_s1}, delta={delta:+.3f}. "
                        "WTT calculation MUST use Σ Scope 1 (source of truth)."
                    ),
                    "blocks_pipeline": False,
                }
            )
            if abs(delta) > 0.001:
                findings.append(
                    {
                        "rule_id": "DQ-WARN-CAT3-DELTA",
                        "severity": "WARN",
                        "scope": 3,
                        "anno": anno,
                        "codice_sito": None,
                        "metric": f"cat3_nonzero_delta_{combustibile}_{anno}",
                        "value_observed": delta,
                        "value_reference": 0.0,
                        "trigger_desc": (
                            f"Non-zero Cat 3 delta for {combustibile} / {anno}: "
                            f"delta={delta:+.3f}. Investigate: stock variation vs. "
                            "out-of-scope volumes? (see methodology_validation §7.3)."
                        ),
                        "blocks_pipeline": False,
                    }
                )
    return findings

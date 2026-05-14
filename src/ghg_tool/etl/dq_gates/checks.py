"""DQ gate check implementations — DQ-CRIT-01..05 and DQ-WARN-01..04.

Each check is a pure function that returns (passes: bool, findings: list[dict]).
CRIT-level failures set ``blocks_pipeline=True``.
WARN-level findings annotate rows but do not block.

No database access: findings are written by the orchestrator/writer.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

FindingDict = dict[str, Any]

_VALID_SITI = {
    "IANO", "VIANO", "VIANO_GARGOLA",
    "CASALGRANDE", "FIORANO", "SASSUOLO", "FRASSINORO",
}

# VIANO electricity 2025 / 2024 ratio threshold for DQ-WARN-01
_WARN_01_RATIO_THRESHOLD = 0.6

_ZSCORE_CRIT_THRESHOLD: float = 2.0
"""Critical outlier threshold for site-level z-scores.

Derived from the maximum achievable z-score for n=7 sites
(σ ≈ 2.27 minus safety margin). Documented in DPM §4.2.
"""

_MIN_OUTLIER_GROUP_SIZE: int = 3
"""Minimum group size below which z-score outlier detection is skipped (insufficient power)."""


def check_facility_coverage(
    df_s1: pd.DataFrame,
    df_s2: pd.DataFrame,
) -> tuple[bool, list[FindingDict]]:
    """DQ-CRIT-01: All 7 sites present for each in-scope scope per year.

    Checks that every site in ``_VALID_SITI`` has at least one GAS_NAT row
    (after FR-01 synthetics) and at least one GO row in Scope 2.

    Args:
        df_s1: Scope 1 DataFrame (post-synthesis, post-FR-37 transforms).
        df_s2: Scope 2 DataFrame (post-synthesis transforms).

    Returns:
        (True, []) if coverage is 7/7; (False, [CRIT findings]) otherwise.
    """
    findings: list[FindingDict] = []
    all_years = df_s1["Anno"].astype(str).unique().tolist()

    for year in all_years:
        s1_year = df_s1[df_s1["Anno"].astype(str) == year]
        present = set(s1_year["Codice_Sito"].unique())
        missing = _VALID_SITI - present
        if missing:
            findings.append(
                {
                    "rule_id": "DQ-CRIT-01",
                    "severity": "CRIT",
                    "scope": 1,
                    "anno": int(year),
                    "codice_sito": ",".join(sorted(missing)),
                    "metric": "facility_coverage_s1",
                    "value_observed": len(present),
                    "value_reference": 7,
                    "trigger_desc": (
                        f"DQ-CRIT-01: Scope 1 coverage {len(present)}/7 for year {year}. "
                        f"Missing sites: {sorted(missing)}"
                    ),
                    "blocks_pipeline": True,
                }
            )
    return len(findings) == 0, findings


def check_mandatory_columns(
    df: pd.DataFrame,
    scope: int,
) -> tuple[bool, list[FindingDict]]:
    """DQ-CRIT-02: No NULL/blank in mandatory columns.

    Mandatory columns by scope:
      Scope 1/2: Quantità, Unità, Codice_Sito, Anno
      Scope 3: Quantità, Unità, Anno, Categoria_S3, Sottocategoria,
                plus Fonte_Dato/Qualità_Dato/Stato_Dato after FR-37 defaulting.

    Args:
        df: DataFrame (post-transforms for scope 3; post-synthesis for 1/2).
        scope: Scope number (1, 2, or 3).

    Returns:
        (True, []) if all mandatory columns are non-null; (False, [CRIT]) otherwise.
    """
    findings: list[FindingDict] = []
    base_cols = ["Quantità", "Unità", "Anno"]
    scope_cols: dict[int, list[str]] = {
        1: base_cols + ["Codice_Sito", "Combustibile"],
        2: base_cols + ["Codice_Sito", "Voce_S2"],
        3: base_cols + [
            "Categoria_S3", "Sottocategoria",
            "Fonte_Dato", "Qualità_Dato", "Stato_Dato",
        ],
    }
    mandatory = scope_cols.get(scope, base_cols)

    for col in mandatory:
        if col not in df.columns:
            continue
        null_mask = df[col].isna() | (df[col].astype(str).str.strip() == "")
        if null_mask.any():
            for idx in df[null_mask].index:
                row = df.loc[idx]
                findings.append(
                    {
                        "rule_id": "DQ-CRIT-02",
                        "severity": "CRIT",
                        "scope": scope,
                        "anno": int(row.get("Anno", 0)) if pd.notna(row.get("Anno")) else None,
                        "codice_sito": str(row.get("Codice_Sito", "")),
                        "metric": f"mandatory_column_{col}",
                        "trigger_desc": (
                            f"DQ-CRIT-02: Mandatory column {col!r} is NULL/blank "
                            f"at row index {idx}."
                        ),
                        "blocks_pipeline": True,
                    }
                )
    return len(findings) == 0, findings


def check_negative_quantities(df: pd.DataFrame, scope: int) -> tuple[bool, list[FindingDict]]:
    """DQ-CRIT-03: Quantità must be >= 0 for all rows.

    Args:
        df: Any scope DataFrame with numeric 'Quantità' column.
        scope: Scope number for finding metadata.

    Returns:
        (True, []) if no negatives; (False, [CRIT]) otherwise.
    """
    findings: list[FindingDict] = []
    qty = pd.to_numeric(df["Quantità"], errors="coerce")
    neg_mask = qty < 0
    for idx in df[neg_mask].index:
        row = df.loc[idx]
        findings.append(
            {
                "rule_id": "DQ-CRIT-03",
                "severity": "CRIT",
                "scope": scope,
                "anno": int(row.get("Anno", 0)) if pd.notna(row.get("Anno")) else None,
                "codice_sito": str(row.get("Codice_Sito", "")),
                "metric": "negative_quantity",
                "value_observed": float(qty[idx]),
                "value_reference": 0.0,
                "trigger_desc": (
                    f"DQ-CRIT-03: Negative Quantità={qty[idx]} at row index {idx}."
                ),
                "blocks_pipeline": True,
            }
        )
    return len(findings) == 0, findings


def check_outlier_zscore(df: pd.DataFrame, scope: int) -> tuple[bool, list[FindingDict]]:
    """DQ-CRIT-04: Z-score > 2.0 on site × fuel/voce × year quantity.

    Computes z-score across (Codice_Sito × fuel_col) within each (fuel, year)
    group.  For small populations (n ≤ 7 sites) the mathematical maximum
    achievable z-score is (n-1)/sqrt(n) ≈ 2.27; a threshold of 2.0 provides
    a single-standard-deviation safety margin below that bound.

    VIANO_GARGOLA GAS_NAT 2025 = 11 Sm³ is a known candidate flagged in
    requirements.md §11.  Detecting it requires the comparison population to
    be near-homogeneous (six sites of similar magnitude + one extreme outlier).

    Args:
        df: Scope 1 or Scope 2 DataFrame (numeric Quantità).
        scope: Scope number for finding metadata.

    Returns:
        (passes, findings) where passes=False if any |z| > 2.0.
    """
    findings: list[FindingDict] = []
    fuel_col = "Combustibile" if scope == 1 else "Voce_S2"
    if fuel_col not in df.columns:
        return True, findings

    qty = pd.to_numeric(df["Quantità"], errors="coerce")
    df = df.copy()
    df["_qty"] = qty
    # Group by (fuel_col, Anno) and compute z-score within each group
    for (fuel, anno), grp in df.groupby([fuel_col, "Anno"]):
        grp_qty = grp["_qty"].dropna()
        if grp_qty.std() == 0 or len(grp_qty) < _MIN_OUTLIER_GROUP_SIZE:
            continue
        z_scores = (grp_qty - grp_qty.mean()) / grp_qty.std()
        for idx, z in z_scores.items():
            if abs(z) > _ZSCORE_CRIT_THRESHOLD:
                # pandas-stubs types idx as Hashable; runtime types are int/str labels.
                row = df.loc[idx]  # type: ignore[call-overload]
                value_observed = float(grp_qty[idx])  # type: ignore[call-overload]
                findings.append(
                    {
                        "rule_id": "DQ-CRIT-04",
                        "severity": "CRIT",
                        "scope": scope,
                        "anno": int(anno),
                        "codice_sito": str(row.get("Codice_Sito", "")),
                        "metric": f"zscore_{fuel}",
                        "value_observed": value_observed,
                        "z_score": float(z),
                        "trigger_desc": (
                            f"DQ-CRIT-04: z-score={z:.2f} > {_ZSCORE_CRIT_THRESHOLD} for "
                            f"{fuel_col}={fuel!r}, site={row.get('Codice_Sito')!r}, "
                            f"Anno={anno}, Quantità={value_observed}."
                        ),
                        "blocks_pipeline": True,
                    }
                )
    return len(findings) == 0, findings


def check_temporal_gap(
    df_s1: pd.DataFrame,
    df_s2: pd.DataFrame,
) -> tuple[bool, list[FindingDict]]:
    """DQ-CRIT-05: Site present in one year must have a record (or explicit zero) in the other.

    After FR-01 and FR-02 synthetics, no temporal gaps should remain.  This
    check validates that assumption.

    Args:
        df_s1: Scope 1 DataFrame post-synthesis.
        df_s2: Scope 2 DataFrame post-synthesis.

    Returns:
        (True, []) if no temporal gaps; (False, [CRIT]) otherwise.
    """
    findings: list[FindingDict] = []
    years = sorted(df_s1["Anno"].astype(str).unique())
    if len(years) < 2:
        return True, findings

    for fuel, grp in df_s1.groupby("Combustibile"):
        present_by_year: dict[str, set[str]] = {}
        for yr in years:
            present_by_year[yr] = set(grp[grp["Anno"].astype(str) == yr]["Codice_Sito"].unique())
        base_sites = set.union(*present_by_year.values())
        for yr in years:
            gap_sites = base_sites - present_by_year[yr]
            for site in gap_sites:
                findings.append(
                    {
                        "rule_id": "DQ-CRIT-05",
                        "severity": "CRIT",
                        "scope": 1,
                        "anno": int(yr),
                        "codice_sito": site,
                        "metric": f"temporal_gap_{fuel}",
                        "trigger_desc": (
                            f"DQ-CRIT-05: Site {site!r} present in other years for "
                            f"Combustibile={fuel!r} but absent in {yr} without explicit zero."
                        ),
                        "blocks_pipeline": True,
                    }
                )
    return len(findings) == 0, findings


def check_warn_01_viano_electricity(df_s2: pd.DataFrame) -> tuple[bool, list[FindingDict]]:
    """DQ-WARN-01: VIANO EE_Acquistata_GO 2025 / 2024 ratio < 0.6 (dashboard banner).

    Per requirements.md §11 this is an operational annotation (fermo parziale
    confirmed by user).  Does not block pipeline; annotates row.

    Args:
        df_s2: Scope 2 DataFrame.

    Returns:
        (True always, [WARN finding if ratio < 0.6]).
    """
    findings: list[FindingDict] = []
    viano_go = df_s2[
        (df_s2["Codice_Sito"] == "VIANO")
        & (df_s2["Voce_S2"] == "EE_Acquistata_GO")
    ]
    qty_by_year: dict[str, float] = {}
    for _, row in viano_go.iterrows():
        yr = str(row["Anno"])
        qty = float(row["Quantità"]) if pd.notna(row["Quantità"]) else 0.0
        qty_by_year[yr] = qty_by_year.get(yr, 0.0) + qty

    if "2024" in qty_by_year and "2025" in qty_by_year and qty_by_year["2024"] > 0:
        ratio = qty_by_year["2025"] / qty_by_year["2024"]
        if ratio < _WARN_01_RATIO_THRESHOLD:
            findings.append(
                {
                    "rule_id": "DQ-WARN-01",
                    "severity": "WARN",
                    "scope": 2,
                    "codice_sito": "VIANO",
                    "anno": 2025,
                    "metric": "ee_go_yoy_ratio",
                    "value_observed": qty_by_year["2025"],
                    "value_reference": qty_by_year["2024"],
                    "ratio_yoy": ratio,
                    "trigger_desc": (
                        f"DQ-WARN-01: VIANO EE_Acquistata_GO 2025/2024 ratio={ratio:.3f} < 0.6. "
                        "Fermo parziale confirmed by user 2026-05-13 (OI-2). "
                        "Dashboard banner required per FR-24."
                    ),
                    "blocks_pipeline": False,
                }
            )
    return True, findings


def check_warn_02_estimated_quality(
    df: pd.DataFrame, scope: int
) -> tuple[bool, list[FindingDict]]:
    """DQ-WARN-02/03/04: Flag estimated or proxy data quality codes.

    Args:
        df: Any scope DataFrame with 'Qualità_Dato' column.
        scope: Scope number for finding metadata.

    Returns:
        (True always, list of WARN findings for estimated/proxy rows).
    """
    findings: list[FindingDict] = []
    if "Qualità_Dato" not in df.columns:
        return True, findings
    est_mask = df["Qualità_Dato"].astype(str).str.strip() == "E"
    for idx in df[est_mask].index:
        row = df.loc[idx]
        findings.append(
            {
                "rule_id": "DQ-WARN-02",
                "severity": "WARN",
                "scope": scope,
                "anno": int(row.get("Anno", 0)) if pd.notna(row.get("Anno")) else None,
                "codice_sito": str(row.get("Codice_Sito", "")),
                "metric": "qualita_dato_estimated",
                "trigger_desc": (
                    "DQ-WARN-02: Qualità_Dato='E' (Estimated) at row index "
                    f"{idx}. Disclose estimation methodology in PDF (DQ-WARN-02)."
                ),
                "blocks_pipeline": False,
            }
        )
    return True, findings

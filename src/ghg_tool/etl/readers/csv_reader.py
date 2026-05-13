"""CSV readers for the three scope input files.

All CSVs are semicolon-delimited, UTF-8 BOM encoded.  Each reader returns a
pandas DataFrame with column names exactly matching the CSV header after
stripping BOM and whitespace.

Import direction: etl → application (OK); etl NEVER imports infrastructure.db
directly (writer does that).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


_SCOPE1_REQUIRED = [
    "Scope", "Anno", "Codice_Sito", "Categoria_S1",
    "Combustibile", "Quantità", "Unità",
    "Fonte_Dato", "Qualità_Dato", "Stato_Dato",
]
_SCOPE2_REQUIRED = [
    "Scope", "Anno", "Codice_Sito", "Voce_S2",
    "Quantità", "Unità", "Strumento_MB",
    "Fonte_Dato", "Qualità_Dato", "Stato_Dato",
]
_SCOPE3_REQUIRED = [
    "Scope", "Anno", "Categoria_S3", "Sottocategoria",
    "Metodo", "Quantità", "Unità",
    "Fonte_Dato", "Qualità_Dato", "Stato_Dato",
]


def _read_csv(path: Path, required_cols: list[str]) -> pd.DataFrame:
    """Load a semicolon-delimited, UTF-8-BOM CSV into a DataFrame.

    Strips BOM, trims column names, and validates that all required columns
    are present.

    Args:
        path: Absolute path to the CSV file.
        required_cols: Column names that must be present after loading.

    Returns:
        Raw pandas DataFrame with original column names.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If any required column is missing.
    """
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    df = pd.read_csv(
        path,
        sep=";",
        encoding="utf-8-sig",  # strips UTF-8 BOM
        dtype=str,             # read all as string; validation done by pandera
        keep_default_na=False, # preserve empty strings vs NaN distinction
    )
    # Normalise column names: strip leading/trailing whitespace
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in {path.name}: {missing}")
    return df


def read_scope1(path: Path) -> pd.DataFrame:
    """Read scope1_combustione.csv into a raw DataFrame.

    Expected: 31 native rows + 1 ETL-synthesised VIANO_GARGOLA zero row
    (added by transforms/synth_rows.py after this read).

    Args:
        path: Path to scope1_combustione.csv.

    Returns:
        DataFrame with scope 1 raw data; 31 native rows.
    """
    return _read_csv(path, _SCOPE1_REQUIRED)


def read_scope2(path: Path) -> pd.DataFrame:
    """Read scope2_elettricita.csv into a raw DataFrame.

    Expected: 15 native rows + 1 ETL-synthesised SASSUOLO Grid 2025 zero row
    (added by transforms/synth_rows.py after this read).

    Args:
        path: Path to scope2_elettricita.csv.

    Returns:
        DataFrame with scope 2 raw data; 15 native rows.
    """
    return _read_csv(path, _SCOPE2_REQUIRED)


def read_scope3(path: Path) -> pd.DataFrame:
    """Read scope3_categorie.csv into a raw DataFrame.

    Expected: 100 native rows.  The 10 Cat 3 WTT/T&D rows have blank
    Fonte_Dato/Qualità_Dato/Stato_Dato metadata — FR-37 defaulting is
    applied by transforms/synth_rows.py after this read.

    Args:
        path: Path to scope3_categorie.csv.

    Returns:
        DataFrame with scope 3 raw data; 100 native rows.
    """
    return _read_csv(path, _SCOPE3_REQUIRED)

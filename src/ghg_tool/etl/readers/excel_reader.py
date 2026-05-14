"""Excel reader for ad-hoc data uploads (FR-03 follow-up).

End users at Gresmalt collect Scope 1 / 2 / 3 activity data in xlsx
workbooks, not CSVs. This reader accepts an in-memory bytes stream
(what Streamlit's file_uploader returns) and produces the same shape
DataFrames the existing CSV reader emits, so the rest of the ETL
pipeline reuses without changes.

The expected workbook is one of:
  1. Three sheets named "Scope1", "Scope2", "Scope3" with the same
     columns as the CSV equivalents.
  2. A single sheet whose name matches the scope label, when uploading
     one scope at a time.

Column names match the canonical Italian schema used in
``etl/readers/csv_reader.py``: Codice_Sito, Quantita, etc.

This module deliberately does NOT touch the DB. The Streamlit page
calls ``parse_workbook`` to get the dataframe, then runs pandera +
DQ-CRIT gates via the existing orchestrator infrastructure, then
asks the user to confirm before any INSERT happens.
"""

from __future__ import annotations

import io
from typing import Final

import pandas as pd

_SCOPE_SHEET_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "scope1": ("Scope1", "Scope 1", "S1", "Scope_1", "scope1"),
    "scope2": ("Scope2", "Scope 2", "S2", "Scope_2", "scope2"),
    "scope3": ("Scope3", "Scope 3", "S3", "Scope_3", "scope3"),
}


_REQUIRED_BY_SCOPE: Final[dict[str, list[str]]] = {
    "scope1": [
        "Scope", "Anno", "Codice_Sito", "Categoria_S1",
        "Combustibile", "Quantità", "Unità",
        "Fonte_Dato", "Qualità_Dato", "Stato_Dato",
    ],
    "scope2": [
        "Scope", "Anno", "Codice_Sito", "Voce_S2",
        "Quantità", "Unità", "Strumento_MB",
        "Fonte_Dato", "Qualità_Dato", "Stato_Dato",
    ],
    "scope3": [
        "Scope", "Anno", "Categoria_S3", "Sottocategoria",
        "Metodo", "Quantità", "Unità",
        "Fonte_Dato", "Qualità_Dato", "Stato_Dato",
    ],
}


class WorkbookParseError(ValueError):
    """Raised when the uploaded workbook does not match any expected layout."""


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace + BOM from column names."""
    df = df.copy()
    df.columns = [str(c).strip().lstrip("﻿") for c in df.columns]
    return df


def _find_sheet(sheet_names: list[str], scope_key: str) -> str | None:
    """Return the actual sheet name matching one of the alias forms, else None."""
    aliases = _SCOPE_SHEET_ALIASES[scope_key]
    lower_alias = {a.lower() for a in aliases}
    for s in sheet_names:
        if s.lower() in lower_alias:
            return s
    return None


def _validate_required(df: pd.DataFrame, scope_key: str) -> list[str]:
    """Return the list of REQUIRED columns missing from ``df`` (empty if OK)."""
    required = _REQUIRED_BY_SCOPE[scope_key]
    return [c for c in required if c not in df.columns]


def parse_workbook(
    raw: bytes,
    *,
    scope_hint: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Parse an uploaded xlsx workbook into one dataframe per scope.

    Args:
        raw: The bytes payload from a Streamlit file_uploader (xlsx).
        scope_hint: Optional 'scope1' / 'scope2' / 'scope3'. When the
            workbook contains a single sheet of that scope, force the
            mapping rather than relying on sheet-name heuristics.

    Returns:
        Mapping of ``"scope1" / "scope2" / "scope3"`` to the parsed
        DataFrame. Scopes not found in the workbook are omitted.

    Raises:
        WorkbookParseError: When no recognisable scope sheet is found
            or the required columns are missing.
    """
    if not raw:
        raise WorkbookParseError("Empty upload payload.")
    try:
        bio = io.BytesIO(raw)
        xls = pd.ExcelFile(bio, engine="openpyxl")
    except (ValueError, OSError) as exc:
        raise WorkbookParseError(
            "Could not parse the upload as a .xlsx workbook."
        ) from exc

    sheet_names = list(xls.sheet_names)
    found: dict[str, pd.DataFrame] = {}

    # If the workbook has exactly one sheet AND a scope_hint is provided,
    # bind it to that scope regardless of the sheet name.
    if scope_hint and scope_hint in _REQUIRED_BY_SCOPE and len(sheet_names) == 1:
        df = _normalise_columns(xls.parse(sheet_names[0]))
        missing = _validate_required(df, scope_hint)
        if missing:
            raise WorkbookParseError(
                f"Sheet for {scope_hint} is missing required columns: {missing}"
            )
        return {scope_hint: df}

    # Otherwise discover by alias.
    for scope_key in ("scope1", "scope2", "scope3"):
        sheet = _find_sheet(sheet_names, scope_key)
        if sheet is None:
            continue
        df = _normalise_columns(xls.parse(sheet))
        missing = _validate_required(df, scope_key)
        if missing:
            raise WorkbookParseError(
                f"Sheet {sheet!r} (mapped to {scope_key}) is missing required "
                f"columns: {missing}"
            )
        found[scope_key] = df

    if not found:
        raise WorkbookParseError(
            "Workbook contains no Scope1 / Scope2 / Scope3 sheet. "
            "Rename your sheets to one of: "
            "Scope1, Scope2, Scope3 (case-insensitive) and try again."
        )

    return found


def summarise_parsed(parsed: dict[str, pd.DataFrame]) -> dict[str, dict[str, int]]:
    """Return a small {scope_key: {rows, years, sites}} summary for the UI.

    Years and sites are counted distinct - useful for the pre-import
    confirmation card.
    """
    out: dict[str, dict[str, int]] = {}
    for scope_key, df in parsed.items():
        years = (
            int(df["Anno"].nunique()) if "Anno" in df.columns else 0
        )
        sites_col = (
            "Codice_Sito" if "Codice_Sito" in df.columns else None
        )
        sites = int(df[sites_col].nunique()) if sites_col else 0
        out[scope_key] = {
            "rows": int(len(df)),
            "years": years,
            "sites": sites,
        }
    return out

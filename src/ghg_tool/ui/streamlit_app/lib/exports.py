"""Shared download / export helpers for Streamlit tables.

Each page that renders a dataframe gets a uniform "download" affordance:
CSV button + Excel button next to the table. Keeps the export UX
consistent across all 9 pages and avoids duplicated boilerplate.

Usage:

    from ghg_tool.ui.streamlit_app.lib.exports import render_download_row

    df = pd.DataFrame(...)
    render_download_row(df, basename="emissions_2025", lang=lang)
    st.dataframe(df)
"""

from __future__ import annotations

import io
from typing import Any

import streamlit as st

from ghg_tool.ui.streamlit_app.lib.i18n import _

# Characters that trigger formula execution in spreadsheet applications when
# they appear as the first character of a cell value (BUG-07 / CSV injection).
_FORMULA_TRIGGER_CHARS: frozenset[str] = frozenset({"=", "+", "-", "@", "\t", "\r"})


def _sanitise_cell(value: Any) -> Any:
    """Prefix any string cell whose first character would trigger a spreadsheet formula.

    Affected characters: ``=``, ``+``, ``-``, ``@``, ``\\t``, ``\\r``.
    A leading single-quote is the universally recognised escape in both Excel and
    LibreOffice Calc; the quote is stored as a literal cell value, not as a formula.

    Non-string values (int, float, Decimal, None, etc.) are returned unchanged.

    Args:
        value: The raw cell value.

    Returns:
        The original value, or a prefixed string when injection risk is detected.
    """
    if isinstance(value, str) and value and value[0] in _FORMULA_TRIGGER_CHARS:
        return "'" + value
    return value


def _sanitise_dataframe(df: Any) -> Any:
    """Return a copy of *df* with all string cells sanitised against formula injection.

    Args:
        df: A pandas DataFrame.  None is returned unchanged.

    Returns:
        A new DataFrame with sanitised cells, or None when df is None.
    """
    if df is None:
        return None
    # applymap was deprecated in pandas 2.1; use map (DataFrame.map) instead.
    # Both operate element-wise on every cell.
    try:
        return df.map(_sanitise_cell)  # pandas >= 2.1
    except AttributeError:
        return df.applymap(_sanitise_cell)  # pandas < 2.1 fallback


def _df_to_csv_bytes(df: Any) -> bytes:
    """Serialise a pandas DataFrame to UTF-8 CSV bytes (formula-injection safe).

    All string cells whose first character is in ``{=, +, -, @, \\t, \\r}`` are
    prefixed with a single quote before serialisation (BUG-07).
    """
    if df is None:
        return b""
    return _sanitise_dataframe(df).to_csv(index=False).encode("utf-8")


def _df_to_xlsx_bytes(df: Any) -> bytes:
    """Serialise a DataFrame to a single-sheet xlsx via openpyxl (formula-injection safe).

    All string cells whose first character is in ``{=, +, -, @, \\t, \\r}`` are
    prefixed with a single quote before serialisation (BUG-07).

    Returns empty bytes on failure so the page never explodes if a row
    contains an unserialisable cell - the user just won't get the Excel
    button click to work; the CSV path is unaffected.
    """
    if df is None:
        return b""
    buf = io.BytesIO()
    try:
        _sanitise_dataframe(df).to_excel(buf, index=False, engine="openpyxl")
    except (ValueError, TypeError):
        return b""
    return buf.getvalue()


def render_download_row(
    df: Any,
    *,
    basename: str,
    lang: str = "it",
    key_prefix: str | None = None,
) -> None:
    """Render CSV + Excel download buttons in a tight two-column row.

    Args:
        df: The pandas DataFrame to export. None / empty is tolerated -
            the buttons still render but yield empty files.
        basename: File name stem (no extension, no path). Final names are
            ``{basename}.csv`` and ``{basename}.xlsx``.
        lang: Active language code.
        key_prefix: Optional key prefix so multiple download rows can
            coexist on the same page without Streamlit "duplicate widget
            ID" errors.
    """
    csv_label = _("download_csv", lang)
    xlsx_label = _("download_excel", lang)
    kp = key_prefix or basename
    col_csv, col_xlsx, _spacer = st.columns([1, 1, 6])
    with col_csv:
        st.download_button(
            label=csv_label,
            data=_df_to_csv_bytes(df),
            file_name=f"{basename}.csv",
            mime="text/csv",
            key=f"dl_csv_{kp}",
        )
    with col_xlsx:
        st.download_button(
            label=xlsx_label,
            data=_df_to_xlsx_bytes(df),
            file_name=f"{basename}.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet"
            ),
            key=f"dl_xlsx_{kp}",
        )

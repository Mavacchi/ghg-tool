"""Shared download / export helpers for Streamlit tables and async jobs.

Each page that renders a dataframe gets a uniform "download" affordance:
CSV button + Excel button next to the table. Keeps the export UX
consistent across all 9 pages and avoids duplicated boilerplate.

Usage::

    from ghg_tool.ui.streamlit_app.lib.exports import render_download_row

    df = pd.DataFrame(...)
    render_download_row(df, basename="emissions_2025", lang=lang)
    st.dataframe(df)

Task 6 — Celery 202 adapter
============================
The ``poll_export_job`` function implements the adapter pattern for the
Celery-backed export endpoints:

  1. POST (caller's responsibility) → 202 Accepted + task_id
  2. ``poll_export_job(job_id, ...)`` polls
     ``GET /api/v1/exports/jobs/{job_id}`` every 2 s (max 60 s).
  3. On SUCCESS (COMPLETED) → fetches bytes from
     ``GET /api/v1/exports/jobs/{job_id}/download`` and renders
     ``st.download_button``.
  4. On FAILURE → ``st.error``.
  5. On timeout (60 s) → warning with manual refresh suggestion.
"""

from __future__ import annotations

import io
import time
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


# ---------------------------------------------------------------------------
# Task 6 — Celery 202 adapter: poll + download
# ---------------------------------------------------------------------------

_POLL_INTERVAL_S: float = 2.0
_POLL_MAX_S: float = 60.0
_TERMINAL_STATUSES: frozenset[str] = frozenset({"COMPLETED", "FAILED"})


def poll_export_job(
    job_id: str,
    *,
    file_basename: str = "ghg_report",
    file_ext: str = "pdf",
    lang: str = "it",
    key_suffix: str = "",
) -> None:
    """Poll an async export job until completion and offer a download button.

    This is the wave-4 adapter for the Celery-backed 202-Accepted export
    pattern.  Callers have already POSTed to ``/api/v1/exports/pdf`` or
    ``/api/v1/exports/xlsx`` and received ``{"job_id": "...", "status":
    "PENDING"}``.  This function drives the polling loop and renders the
    appropriate Streamlit widgets.

    Flow::

        POST → 202 (caller) → poll_export_job(job_id, ...) →
          PENDING / RUNNING: spinner loop every 2 s, max 60 s
          COMPLETED:  GET .../download → st.download_button
          FAILED:     st.error with error_message
          timeout:    st.warning with manual refresh suggestion

    Args:
        job_id: UUID string of the export job.
        file_basename: File name stem for the download button (no extension).
        file_ext: File extension without leading dot (``"pdf"`` or ``"xlsx"``).
        lang: Active language code (used for i18n labels).
        key_suffix: Optional key suffix to avoid Streamlit widget-key conflicts
            when multiple export jobs are shown on the same page.

    Returns:
        None.  All output is rendered via Streamlit widgets.
    """
    from ghg_tool.ui.streamlit_app.lib.api_client import (  # noqa: PLC0415
        download_report,
        fetch_job_status,
    )

    if not job_id:
        return

    mime_map = {
        "pdf": "application/pdf",
        "xlsx": (
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet"
        ),
    }
    mime = mime_map.get(file_ext.lower(), "application/octet-stream")
    file_name = f"{file_basename}.{file_ext}"
    dl_key = f"dl_{file_ext}_{job_id}{key_suffix}"

    elapsed = 0.0
    final_status: str = ""
    status_data: dict[str, Any] = {}

    spinner_label = "Generazione in corso..."
    with st.spinner(spinner_label):
        while elapsed < _POLL_MAX_S:
            status_data = fetch_job_status(job_id)
            final_status = status_data.get("status", "UNKNOWN")
            if final_status in _TERMINAL_STATUSES:
                break
            time.sleep(_POLL_INTERVAL_S)
            elapsed += _POLL_INTERVAL_S

    if final_status == "COMPLETED":
        # Prefer a pre-signed download_url when the backend provides one;
        # fall back to direct byte fetch.
        download_url = status_data.get("download_url")
        if download_url:
            # Validate URL safety before rendering as hyperlink.
            if isinstance(download_url, str):
                lo = download_url.strip().lower()
                if lo.startswith(("https://", "http://", "/")):
                    st.download_button(
                        label=f"Scarica {file_ext.upper()}",
                        data=download_url,
                        file_name=file_name,
                        mime=mime,
                        key=dl_key,
                    )
                    return
        # Fetch bytes directly from the download endpoint.
        file_bytes = download_report(job_id)
        if file_bytes:
            st.download_button(
                label=f"Scarica {file_ext.upper()}",
                data=file_bytes,
                file_name=file_name,
                mime=mime,
                key=dl_key,
            )
        else:
            st.warning(
                "Export completato ma file non disponibile. "
                "Ricarica la pagina e riprova.",
                icon="⚠️",
            )
    elif final_status == "FAILED":
        err_msg = status_data.get("error_message") or "Errore sconosciuto."
        st.error(f"Generazione fallita: {err_msg}", icon="🚫")
    else:
        # Timeout or unknown status
        st.warning(
            f"La generazione richiede più tempo del previsto (>{int(_POLL_MAX_S)}s). "
            f"Job ID: `{job_id}`. "
            "Ricarica la pagina per verificare lo stato.",
            icon="⏳",
        )

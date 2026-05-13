"""Reports & Export page (FR-27, FR-28).

Two export flows:
  1. PDF (ESRS E1-6 + E1-7) — POST /api/v1/reports/pdf → poll → download link
  2. Excel multi-sheet     — POST /api/v1/reports/excel → poll → download link

Also provides in-browser Excel generation via XlsxBuilder (bypass API for demo).
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Reports Export — GHG", layout="wide")

from ghg_tool.ui.streamlit_app.Home import DASHBOARD_ID, DASHBOARD_VERSION  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.api_client import (  # noqa: E402
    trigger_pdf_report,
    trigger_excel_report,
    fetch_job_status,
)

require_auth()
lang = get_lang()

# ---------------------------------------------------------------------------
# Helper — inline PDF generation (defined before use)
# ---------------------------------------------------------------------------


def _generate_inline_pdf(anno: int, gwp_set: str, report_lang: str) -> None:
    """Generate PDF inline and offer download button.

    Args:
        anno: Reporting year.
        gwp_set: GWP set.
        report_lang: Language code.
    """
    try:
        from ghg_tool.ui.pdf.builder import PDFBuilder  # noqa: PLC0415
        builder = PDFBuilder()
        pdf_bytes = builder.build({
            "anno": anno,
            "gwp_set": gwp_set,
            "language": report_lang,
            "emissions": [],
            "biogenic": [],
            "factors": [],
            "dq_findings": [],
            "audit_trail": [],
        })
        st.download_button(
            label=_("download_pdf", report_lang),
            data=pdf_bytes,
            file_name=f"ghg_esrs_e1_{anno}_{gwp_set}.pdf",
            mime="application/pdf",
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Errore generazione PDF: {exc}")


# ---------------------------------------------------------------------------
# Page title
# ---------------------------------------------------------------------------
st.title(_("nav_reports", lang))

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    anno = st.selectbox(_("year_filter", lang), [2024, 2025], index=1)
    gwp_set = st.selectbox("GWP Set", ["AR6", "AR5"])
    report_lang = st.selectbox("Report language", ["it", "en"])

# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------
st.subheader(f"Genera PDF — ESRS E1-6 + E1-7")
st.caption("ESRS E1-6 + E1-7 | WeasyPrint | VIANO 2025 disclosure se applicabile")

col_pdf, col_pdf_status = st.columns([1, 2])

with col_pdf:
    if st.button(_("generate_pdf", lang), key="btn_pdf"):
        result = trigger_pdf_report(anno=anno, gwp_set=gwp_set, language=report_lang)
        if "error" in result:
            st.error(f"{_('job_failed', lang)}: {result['error']}")
        else:
            job_id = result.get("job_id", "")
            st.session_state["pdf_job_id"] = job_id
            st.success(f"Job avviato: {job_id}")

with col_pdf_status:
    job_id_pdf = st.session_state.get("pdf_job_id", "")
    if job_id_pdf:
        st.caption(f"Job ID: `{job_id_pdf}`")
        status_data = fetch_job_status(job_id_pdf)
        status = status_data.get("status", "UNKNOWN")

        status_label = {
            "PENDING": _("job_pending", lang),
            "RUNNING": _("job_running", lang),
            "COMPLETED": _("job_done", lang),
            "FAILED": _("job_failed", lang),
        }.get(status, status)

        st.write(f"Stato: **{status_label}**")

        if status == "COMPLETED":
            download_url = status_data.get("download_url")
            if download_url:
                st.markdown(f"[Scarica PDF]({download_url})")
            else:
                _generate_inline_pdf(anno, gwp_set, report_lang)
        elif status == "FAILED":
            st.error(status_data.get("error_message", "Errore sconosciuto"))

st.divider()

# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------
st.subheader(f"Genera Excel — Multi-foglio")
st.caption("11 fogli | Metadata per cella | Okabe-Ito header fill")

col_xls, col_xls_status = st.columns([1, 2])

with col_xls:
    if st.button(_("generate_excel", lang), key="btn_excel"):
        result = trigger_excel_report(anno=anno, gwp_set=gwp_set)
        if "error" in result:
            st.error(f"{_('job_failed', lang)}: {result['error']}")
        else:
            job_id = result.get("job_id", "")
            st.session_state["xlsx_job_id"] = job_id
            st.success(f"Job avviato: {job_id}")

    if st.button("Genera Excel in-browser (demo)", key="btn_excel_inline"):
        from ghg_tool.ui.excel.builder import XlsxBuilder  # noqa: PLC0415
        builder = XlsxBuilder()
        xlsx_bytes = builder.build({
            "anno": anno,
            "gwp_set": gwp_set,
            "emissions": [],
            "factors": [],
            "dq_findings": [],
            "audit_trail": [],
        })
        st.download_button(
            label=_("download_excel", lang),
            data=xlsx_bytes,
            file_name=f"ghg_report_{anno}_{gwp_set}.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet"
            ),
        )

with col_xls_status:
    job_id_xlsx = st.session_state.get("xlsx_job_id", "")
    if job_id_xlsx:
        st.caption(f"Job ID: `{job_id_xlsx}`")
        status_data = fetch_job_status(job_id_xlsx)
        status = status_data.get("status", "UNKNOWN")

        status_label = {
            "PENDING": _("job_pending", lang),
            "RUNNING": _("job_running", lang),
            "COMPLETED": _("job_done", lang),
            "FAILED": _("job_failed", lang),
        }.get(status, status)

        st.write(f"Stato: **{status_label}**")
        if status == "COMPLETED":
            download_url = status_data.get("download_url")
            if download_url:
                st.markdown(f"[Scarica Excel]({download_url})")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    f"GWP set: {gwp_set} | {_('footer_factor_source', lang)} | "
    f"{_('footer_methodology', lang)}"
)

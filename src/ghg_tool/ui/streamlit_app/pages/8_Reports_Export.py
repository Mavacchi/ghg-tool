"""Reports & Export page (FR-27, FR-28).

Two export flows:
  1. PDF (ESRS E1-6 + E1-7) — POST /api/v1/exports/pdf → poll → download link
  2. Excel multi-sheet     — POST /api/v1/exports/xlsx → poll → download link

Also provides in-browser Excel generation via XlsxBuilder (bypass API for demo).
"""

from __future__ import annotations

import structlog
import streamlit as st

_logger = structlog.get_logger(__name__)

from ghg_tool.ui.streamlit_app.lib.constants import (
    DASHBOARD_ID, DASHBOARD_VERSION, PRODUCT_NAME, page_icon,
)

st.set_page_config(
    page_title=f"Reports Export · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.brand import apply_brand_chrome  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.filters import sidebar_gwp_filter, sidebar_year_filter  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.help import _help  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.api_client import (  # noqa: E402
    trigger_pdf_report,
    trigger_excel_report,
    fetch_job_status,
)

apply_brand_chrome()
require_auth()
lang = get_lang()

# ---------------------------------------------------------------------------
# Helper — inline PDF generation (defined before use)
# ---------------------------------------------------------------------------


def _is_safe_download_url(url: str) -> bool:
    """Return True if the URL is safe to render as a hyperlink.

    Rejects ``javascript:``, ``data:``, ``file:`` and other unsafe schemes
    that could trigger XSS or local-file disclosure when clicked.
    Also rejects protocol-relative URLs (``//evil.example``) which the
    browser would resolve under the current scheme to a foreign origin.
    """
    if not isinstance(url, str) or not url:
        return False
    lowered = url.strip().lower()
    if lowered.startswith("//"):
        return False
    if lowered.startswith(("https://", "http://")):
        return True
    # Same-origin absolute paths (must start with a single '/').
    return lowered.startswith("/")


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
    except (ImportError, OSError, ValueError, RuntimeError):
        # REV-WAVE3-015: narrow catch covers missing WeasyPrint (ImportError),
        # font/resource I/O errors (OSError), malformed report data (ValueError),
        # and pydyf/cairo runtime failures (RuntimeError). The raw exception
        # is logged for diagnosis but NOT shown to the end user (information
        # disclosure risk).
        _logger.exception("inline_pdf_generation_failed", anno=anno, gwp_set=gwp_set)
        st.error(_("pdf_error_msg", report_lang))


# ---------------------------------------------------------------------------
# Page title
# ---------------------------------------------------------------------------
st.title(_("nav_reports", lang))

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    anno = sidebar_year_filter(lang)
    gwp_set = sidebar_gwp_filter(lang)
    report_lang = st.selectbox(_("report_lang_label", lang), ["it", "en"])

# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------
st.subheader(_("generate_pdf", lang))
st.caption(_("pdf_subtitle", lang))
st.caption(f"ℹ️ {_help('esrs_e1', lang)}")

col_pdf, col_pdf_status = st.columns([1, 2])

with col_pdf:
    if st.button(_("generate_pdf", lang), key="btn_pdf", help=_help("esrs_e1", lang)):
        result = trigger_pdf_report(anno=anno, gwp_set=gwp_set, language=report_lang)
        if "error" in result:
            st.error(f"{_('job_failed', lang)}: {result['error']}")
        else:
            job_id = result.get("job_id", "")
            st.session_state["pdf_job_id"] = job_id
            st.success(f"{_('job_started', lang)} {job_id}")

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

        st.write(f"{_('status_label', lang)} **{status_label}**")

        if status == "COMPLETED":
            download_url = status_data.get("download_url")
            if download_url and _is_safe_download_url(download_url):
                st.link_button("Scarica PDF", download_url)
            else:
                _generate_inline_pdf(anno, gwp_set, report_lang)
        elif status == "FAILED":
            st.error(status_data.get("error_message", "Errore sconosciuto"))

st.divider()

# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------
st.subheader(_("generate_excel", lang))
st.caption(_("excel_subtitle", lang))

col_xls, col_xls_status = st.columns([1, 2])

with col_xls:
    if st.button(_("generate_excel", lang), key="btn_excel"):
        result = trigger_excel_report(anno=anno, gwp_set=gwp_set)
        if "error" in result:
            st.error(f"{_('job_failed', lang)}: {result['error']}")
        else:
            job_id = result.get("job_id", "")
            st.session_state["xlsx_job_id"] = job_id
            st.success(f"{_('job_started', lang)} {job_id}")

    if st.button(_("excel_inline_btn", lang), key="btn_excel_inline"):
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

        st.write(f"{_('status_label', lang)} **{status_label}**")
        if status == "COMPLETED":
            download_url = status_data.get("download_url")
            if download_url and _is_safe_download_url(download_url):
                st.link_button(_("download_excel", lang), download_url)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    f"GWP set: {gwp_set} | {_('footer_factor_source', lang)} | "
    f"{_('footer_methodology', lang)}"
)

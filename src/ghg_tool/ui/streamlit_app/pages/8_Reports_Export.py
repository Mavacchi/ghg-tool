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
from ghg_tool.ui.streamlit_app.lib.brand import apply_brand_chrome, render_context_bar, render_role_chip  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.filters import sidebar_gwp_filter, sidebar_year_filter  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.help import _help  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.api_client import (  # noqa: E402
    trigger_pdf_report,
    trigger_excel_report,
    fetch_job_status,
    download_report,
    fetch_kpis,
    fetch_emissions,
    fetch_dq_findings,
)

apply_brand_chrome()
require_auth()
lang = get_lang()

# ---------------------------------------------------------------------------
# Helper — executive PDF generation
# ---------------------------------------------------------------------------


def _compute_top_scope3(rows: list[dict], top_n: int = 5) -> list[dict]:
    """Aggregate Scope 3 emission rows into top-N categories by tCO2e.

    Args:
        rows: Raw emission rows for scope 3.
        top_n: Maximum categories to return.

    Returns:
        List of dicts with keys sub_scope, category_label, tco2e, pct.
    """
    from collections import defaultdict
    totals: dict[str, float] = defaultdict(float)
    for r in rows:
        sub = str(r.get("sub_scope") or "Unknown")
        totals[sub] += float(r.get("tco2e") or 0)

    grand = sum(totals.values()) or 1.0
    ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:top_n]

    result = []
    for sub, val in ranked:
        result.append({
            "sub_scope": sub,
            "category_label": sub,
            "tco2e": val,
            "pct": round(val / grand * 100, 1),
        })
    return result


def _generate_exec_pdf(anno: int, gwp_set: str, report_lang: str) -> None:
    """Generate the executive one-pager PDF and offer a download button.

    Fetches KPIs for current and prior year, computes Scope 3 hot-spots, and
    delegates rendering to ExecDashboardBuilder. Gracefully no-ops on any
    data fetch failure without crashing the page.

    Args:
        anno: Current reporting year.
        gwp_set: GWP characterisation set.
        report_lang: Language code ('it' or 'en').
    """
    try:
        from ghg_tool.ui.pdf.exec_dashboard import ExecDashboardBuilder  # noqa: PLC0415
    except ImportError:
        st.error("ExecDashboardBuilder non disponibile.")
        return

    prior_anno = anno - 1

    with st.spinner("Recupero dati KPI..."):
        kpis_cur = fetch_kpis(anno=anno, gwp_set=gwp_set)
        kpis_pri = fetch_kpis(anno=prior_anno, gwp_set=gwp_set)

    # Normalise totals from the KPI response shape
    def _totals(kpis: dict) -> dict:
        return {
            "scope1": kpis.get("scope1_total") or kpis.get("scope1") or 0.0,
            "scope2_lb": kpis.get("scope2_lb_total") or kpis.get("scope2_lb") or 0.0,
            "scope2_mb": kpis.get("scope2_mb_total") or kpis.get("scope2_mb") or 0.0,
            "scope3": kpis.get("scope3_total") or kpis.get("scope3") or 0.0,
            "biogenic_memo": kpis.get("biogenic_total_co2") or None,
            "total_lb": None,  # will be computed in ExecDashboardBuilder
        }

    totals_current = _totals(kpis_cur)
    totals_prior = _totals(kpis_pri)

    # Scope 3 hot-spots
    with st.spinner("Recupero Scope 3..."):
        s3_rows = fetch_emissions(scope=3, anno=anno, gwp_set=gwp_set)
    top_scope3 = _compute_top_scope3(s3_rows)

    # DQ summary
    with st.spinner("Recupero DQ findings..."):
        dq_rows = fetch_dq_findings(resolution_status="OPEN")
    crit_open = sum(1 for r in dq_rows if r.get("severity") == "CRIT")
    warn_open = sum(1 for r in dq_rows if r.get("severity") == "WARN")
    dq_summary = {
        "crit_open": crit_open,
        "warn_open": warn_open,
        "total_findings": len(dq_rows),
    }

    data = {
        "anno": anno,
        "prior_anno": prior_anno,
        "company_name": kpis_cur.get("company_name", ""),
        "gwp_set": gwp_set,
        "language": report_lang,
        "totals_current": totals_current,
        "totals_prior": totals_prior,
        "intensity_revenue": kpis_cur.get("intensity_revenue"),
        "intensity_m2": kpis_cur.get("intensity_m2"),
        "intensity_revenue_prior": kpis_pri.get("intensity_revenue"),
        "intensity_m2_prior": kpis_pri.get("intensity_m2"),
        "target": kpis_cur.get("sbti_target"),
        "top_scope3_categories": top_scope3,
        "dq_summary": dq_summary,
        "assurance_status": kpis_cur.get("assurance_status", "none"),
        "signed_by_esg_manager": None,
    }

    try:
        pdf_bytes = ExecDashboardBuilder().build(data)
        st.download_button(
            label="Scarica PDF Executive" if report_lang == "it" else "Download Executive PDF",
            data=pdf_bytes,
            file_name=f"exec_dashboard_{anno}_{gwp_set}.pdf",
            mime="application/pdf",
        )
    except (ImportError, OSError, ValueError, RuntimeError):
        _logger.exception("exec_pdf_generation_failed", anno=anno, gwp_set=gwp_set)
        st.error("Errore durante la generazione del PDF executive. Riprovare.")


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

render_role_chip(st.session_state.get("role"), lang)

render_context_bar(
    lang=lang,
    year=anno,
    gwp=gwp_set,
    role=st.session_state.get("role"),
)

# ---------------------------------------------------------------------------
# Executive Dashboard (one-pager)
# ---------------------------------------------------------------------------
st.subheader("Executive Dashboard (1 pagina)")
st.caption(
    "Board pack one-pager: KPI, trend Scope 1/2/3, target SBTi, "
    "hot-spot Scope 3, metriche di intensita, DQ status."
)

col_exec_prev, col_exec_gen = st.columns([1, 1])

with col_exec_prev:
    st.markdown("**Anteprima struttura**")
    st.markdown(
        """
        - Riga 1: 5 KPI card (Totale, S1, S2 LB, S2 MB, S3) con delta YoY
        - Riga 2: Grafico barre S1/S2/S3 | Tracker target SBTi
        - Riga 3: Top-5 categorie Scope 3 | Intensita (tCO2e/MEUR, kgCO2e/m2)
        - Riga 4: DQ status + Assurance + firma ESG Manager
        - Footer: dashboard ID, GWP set, methodology, disclaimer ADR-007
        """
    )

with col_exec_gen:
    st.markdown("**Genera PDF Executive**")
    if st.button("Genera PDF Executive", key="btn_exec_pdf"):
        _generate_exec_pdf(anno, gwp_set, report_lang)

st.divider()

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
            else:
                # download_url is absent (in-process render stores bytes
                # server-side, not as a pre-signed URL).  Fetch the raw
                # bytes via GET /api/v1/exports/jobs/{job_id}/download and
                # offer a real st.download_button so the browser triggers
                # a file-save dialog.
                xlsx_bytes = download_report(job_id_xlsx)
                if xlsx_bytes:
                    st.download_button(
                        label=_("download_excel", lang),
                        data=xlsx_bytes,
                        file_name=f"ghg_report_{job_id_xlsx}.xlsx",
                        mime=(
                            "application/vnd.openxmlformats-officedocument"
                            ".spreadsheetml.sheet"
                        ),
                        key=f"dl_xlsx_{job_id_xlsx}",
                    )
                else:
                    st.warning(
                        "Report completato ma file non disponibile. "
                        "Riprovare tra qualche secondo."
                    )
        elif status == "FAILED":
            st.error(status_data.get("error_message", "Errore sconosciuto"))

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    f"GWP set: {gwp_set} | {_('footer_factor_source', lang)} | "
    f"{_('footer_methodology', lang)}"
)

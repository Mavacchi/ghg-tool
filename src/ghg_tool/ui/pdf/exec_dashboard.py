"""ExecDashboardBuilder -- renders the one-page executive dashboard PDF.

Produces a single A4 portrait page suitable for board packs and CFO review
before filing. Uses WeasyPrint for HTML-to-PDF conversion with a matplotlib
chart embedded as a base64 data URI (no live network calls during render).

ADR-007: Biogenic emissions are shown as a memo item ONLY and are never
included in Scope 1/2/3 totals.

Usage::

    builder = ExecDashboardBuilder()
    pdf_bytes = builder.build(data)
    assert pdf_bytes[:4] == b"%PDF"

Data dict keys documented in ``build()`` docstring.
"""

from __future__ import annotations

import base64
import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_CSS_PATH = _TEMPLATES_DIR / "exec_dashboard.css"

EXEC_DASHBOARD_VERSION = "1.0.0"
EXEC_DASHBOARD_ID = "esg-exec-2026"

# ---------------------------------------------------------------------------
# Okabe-Ito colours for chart series (colorblind-safe)
# ---------------------------------------------------------------------------
_OI_VERMILION = "#D55E00"    # Scope 1
_OI_BLUE = "#0072B2"         # Scope 2 LB
_OI_BLUISH_GREEN = "#009E73"  # Scope 3

# Traffic-light status -> CSS class mapping
_STATUS_CSS: dict[str, str] = {
    "ON_TRACK": "on-track",
    "SLIGHTLY_OFF": "slightly-off",
    "OFF_TRACK": "off-track",
    "NO_DATA": "no-data",
}

# ---------------------------------------------------------------------------
# i18n copy -- IT / EN
# ---------------------------------------------------------------------------
_LABELS: dict[str, dict[str, str]] = {
    "it": {
        "label_reporting_year": "Anno di rendicontazione",
        "label_generated": "Generato",
        "label_total": "Totale GHG",
        "label_vs": "vs",
        "label_vs_short": "vs",
        "label_emissions_by_scope": "Emissioni per Scope",
        "label_chart_alt": "Grafico emissioni Scope 1/2/3 confronto anno precedente",
        "label_sbti_target": "Target SBTi",
        "label_target_year": "Anno target",
        "label_target_tco2e": "Target tCO2e",
        "label_no_target": "Nessun target SBTi attivo",
        "label_scope3_hotspots": "Top 5 categorie Scope 3",
        "label_category": "Categoria",
        "label_no_data": "Nessun dato disponibile",
        "label_intensity": "Metriche di intensita",
        "label_metric": "Metrica",
        "label_biogenic_memo": "Biogenico (memo)",
        "label_dq_status": "Qualita dati (DQ)",
        "label_total_findings": "totali",
        "label_assurance": "Assurance",
        "label_esg_manager": "Data Owner",
        "label_date": "Data",
        "label_dashboard": "Dashboard",
        "label_factor_sources": "Fonti fattori",
        "label_methodology": "Metodologia",
        "label_biogenic_disclaimer": (
            "Le emissioni biogeniche di CO2 dalla combustione di biomasse e biogas "
            "sono disclosed separatamente. Non sono incluse nei totali Scope 1/2/3 "
            "ai sensi di ADR-007 e del GHG Protocol Corporate Standard par. 4.5."
        ),
    },
    "en": {
        "label_reporting_year": "Reporting year",
        "label_generated": "Generated",
        "label_total": "Total GHG",
        "label_vs": "vs",
        "label_vs_short": "vs",
        "label_emissions_by_scope": "Emissions by Scope",
        "label_chart_alt": "Scope 1/2/3 emissions chart vs prior year",
        "label_sbti_target": "SBTi Target",
        "label_target_year": "Target year",
        "label_target_tco2e": "Target tCO2e",
        "label_no_target": "No active SBTi target",
        "label_scope3_hotspots": "Top 5 Scope 3 categories",
        "label_category": "Category",
        "label_no_data": "No data available",
        "label_intensity": "Intensity metrics",
        "label_metric": "Metric",
        "label_biogenic_memo": "Biogenic (memo)",
        "label_dq_status": "Data quality (DQ)",
        "label_total_findings": "total",
        "label_assurance": "Assurance",
        "label_esg_manager": "Data Owner",
        "label_date": "Date",
        "label_dashboard": "Dashboard",
        "label_factor_sources": "Factor sources",
        "label_methodology": "Methodology",
        "label_biogenic_disclaimer": (
            "Biogenic CO2 emissions from biomass and biogas combustion are disclosed "
            "separately. They are NOT included in Scope 1/2/3 totals per ADR-007 "
            "and GHG Protocol Corporate Standard sec. 4.5."
        ),
    },
}


def _labels(language: str) -> dict[str, str]:
    """Return the label dict for the requested language (falls back to 'it')."""
    return _LABELS.get(language, _LABELS["it"])


# ---------------------------------------------------------------------------
# Delta computation helpers
# ---------------------------------------------------------------------------

def _pct_delta(current: float | None, prior: float | None) -> dict[str, Any] | None:
    """Compute percentage change between two values.

    Returns a dict with keys ``pct``, ``arrow``, ``css``; or None when either
    value is missing or prior is zero.
    """
    if current is None or prior is None or prior == 0.0:
        return None
    raw = (current - prior) / abs(prior) * 100.0
    pct = round(raw, 1)
    if raw > 0.5:
        return {"pct": f"+{pct}", "arrow": "^", "css": "up"}
    if raw < -0.5:
        return {"pct": str(pct), "arrow": "v", "css": "down"}
    return {"pct": "0.0", "arrow": "=", "css": "flat"}


# ---------------------------------------------------------------------------
# Matplotlib chart builder (headless, no network)
# ---------------------------------------------------------------------------

def _build_chart_png(
    current: dict[str, Any],
    prior: dict[str, Any],
    anno: int,
    prior_anno: int,
) -> bytes:
    """Render a grouped bar chart and return PNG bytes.

    Uses the Agg backend exclusively -- no display required and no network
    resources are fetched.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    scopes = ["Scope 1", "Scope 2 LB", "Scope 3"]
    values_cur = [
        float(current.get("scope1", 0) or 0),
        float(current.get("scope2_lb", 0) or 0),
        float(current.get("scope3", 0) or 0),
    ]
    values_pri = [
        float(prior.get("scope1", 0) or 0),
        float(prior.get("scope2_lb", 0) or 0),
        float(prior.get("scope3", 0) or 0),
    ]

    x = np.arange(len(scopes))
    width = 0.35

    fig, ax = plt.subplots(figsize=(3.5, 2.0), dpi=130)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")

    ax.bar(
        x - width / 2, values_pri, width,
        label=str(prior_anno),
        color=["#D55E00", "#0072B2", "#009E73"],
        alpha=0.45,
        edgecolor="none",
    )
    ax.bar(
        x + width / 2, values_cur, width,
        label=str(anno),
        color=["#D55E00", "#0072B2", "#009E73"],
        alpha=0.95,
        edgecolor="none",
    )

    ax.set_xticks(x)
    ax.set_xticklabels(scopes, fontsize=6)
    ax.yaxis.set_tick_params(labelsize=5)
    ax.set_ylabel("tCO2e", fontsize=5.5)
    ax.legend(fontsize=5.5, frameon=False, loc="upper right")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#ECE5DC")
    ax.spines["bottom"].set_color("#ECE5DC")
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}")
    )
    ax.tick_params(colors="#1a1a1a")

    fig.tight_layout(pad=0.4)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _png_to_data_uri(png_bytes: bytes) -> str:
    """Encode PNG bytes as a base64 data URI for inline HTML embedding."""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# Jinja2 custom filters
# ---------------------------------------------------------------------------

def _fmt_num(value: Any) -> str:
    """Format a number as thousands-separated integer string."""
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_dec(value: Any) -> str:
    """Format a number with two decimal places."""
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "N/A"


# ---------------------------------------------------------------------------
# Fallback HTML (no Jinja2 / no WeasyPrint)
# ---------------------------------------------------------------------------

def _fallback_html_exec(ctx: dict[str, Any]) -> str:
    """Minimal HTML for ExecDashboard when Jinja2 is not available."""
    anno = ctx.get("anno", "")
    gwp_set = ctx.get("gwp_set", "AR6")
    generated_at = ctx.get("generated_at", "")
    dashboard_id = ctx.get("dashboard_id", EXEC_DASHBOARD_ID)
    dashboard_version = ctx.get("dashboard_version", EXEC_DASHBOARD_VERSION)
    company_name = ctx.get("company_name", "")
    totals = ctx.get("totals_current", {})
    total_lb = totals.get("total_lb", 0)
    dq = ctx.get("dq_summary", {})
    assurance = ctx.get("assurance_status", "none")

    return f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<title>Executive Dashboard {anno}</title>
<style>
@page {{ size: A4 portrait; margin: 12mm; }}
body {{ font-family: Arial, sans-serif; font-size: 9pt; color: #1a1a1a; }}
h1 {{ font-size: 14pt; color: #788B99; }}
</style>
</head>
<body>
<h1>Carbontrace - Executive Dashboard</h1>
<p><strong>{company_name}</strong> | Anno: {anno} | Generato: {generated_at}</p>
<p>Totale GHG (S1+S2 LB+S3): <strong>{_fmt_num(total_lb)} tCO2e</strong></p>
<p>Scope 1: {_fmt_num(totals.get("scope1", 0))} tCO2e |
   Scope 2 LB: {_fmt_num(totals.get("scope2_lb", 0))} tCO2e |
   Scope 2 MB: {_fmt_num(totals.get("scope2_mb", 0))} tCO2e |
   Scope 3: {_fmt_num(totals.get("scope3", 0))} tCO2e</p>
<p>DQ: {dq.get("crit_open", 0)} CRIT, {dq.get("warn_open", 0)} WARN,
   {dq.get("total_findings", 0)} totali | Assurance: {assurance}</p>
<p>GWP set: {gwp_set} | Metodologia: GHG Protocol Corporate Standard</p>
<p>Dashboard: {dashboard_id} v{dashboard_version}</p>
<p><em>ADR-007: Le emissioni biogeniche di CO2 dalla combustione di biomasse e biogas
sono disclosed separatamente. Non sono incluse nei totali Scope 1/2/3
ai sensi di ADR-007 e del GHG Protocol Corporate Standard par. 4.5.</em></p>
<p><em>Generato con template di fallback -- Jinja2 non disponibile.</em></p>
</body></html>"""


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

class ExecDashboardBuilder:
    """Renders a one-page executive dashboard PDF via WeasyPrint.

    The builder is a pure renderer: it never calculates emission values.
    All numeric data must be pre-validated and supplied via the ``data`` dict.
    """

    def __init__(self) -> None:
        """Initialise the builder and load the Jinja2 environment."""
        self._jinja_env: Any = None
        try:
            import jinja2

            env = jinja2.Environment(
                loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
                autoescape=jinja2.select_autoescape(["html"]),
            )
            env.filters["fmt_num"] = _fmt_num
            env.filters["fmt_dec"] = _fmt_dec
            self._jinja_env = env
        except ImportError:
            logger.warning("jinja2_not_installed", msg="ExecDashboard will use fallback HTML")

    # ------------------------------------------------------------------

    def build(self, data: dict[str, Any]) -> bytes:
        """Return PDF bytes for the executive one-pager.

        ``data`` keys:

        Required:
          - anno: int -- reporting year
          - prior_anno: int -- year-prior for YoY delta
          - company_name: str
          - gwp_set: str -- e.g. 'AR6'
          - language: str -- 'it' or 'en'
          - totals_current: dict with keys scope1, scope2_lb, scope2_mb,
              scope3, biogenic_memo (float|None), total_lb (float|None)
          - totals_prior: same shape as totals_current
          - intensity_revenue: float|None -- tCO2e/MEUR current year
          - intensity_m2: float|None -- kgCO2e/m2 current year
          - dq_summary: dict with keys crit_open, warn_open, total_findings
          - assurance_status: 'limited' | 'reasonable' | 'none'

        Optional:
          - generated_at: str -- ISO timestamp; defaults to now()
          - dashboard_id: str -- defaults to EXEC_DASHBOARD_ID
          - dashboard_version: str -- defaults to EXEC_DASHBOARD_VERSION
          - target: dict|None with keys name, target_year, target_tco2e,
              on_track_status ('ON_TRACK'|'SLIGHTLY_OFF'|'OFF_TRACK'|'NO_DATA'),
              trajectory_note (str|None)
          - top_scope3_categories: list of dicts {sub_scope, category_label,
              tco2e, pct}; defaults to []
          - signed_by_esg_manager: str|None
          - intensity_revenue_prior: float|None -- for YoY delta
          - intensity_m2_prior: float|None -- for YoY delta

        Returns:
            PDF bytes starting with b'%PDF'.
        """
        import weasyprint

        ctx = self._build_context(data)
        html_content = self._render_html(ctx)

        log = logger.bind(
            anno=ctx["anno"],
            gwp_set=ctx["gwp_set"],
            dashboard_id=ctx["dashboard_id"],
        )
        log.info("exec_dashboard_pdf_rendering")

        html_obj = weasyprint.HTML(string=html_content, base_url=str(_TEMPLATES_DIR))
        pdf_bytes: bytes = html_obj.write_pdf()

        log.info("exec_dashboard_pdf_done", size_bytes=len(pdf_bytes))
        return pdf_bytes

    # ------------------------------------------------------------------

    def _build_context(self, data: dict[str, Any]) -> dict[str, Any]:
        """Assemble the Jinja2 template context from ``data``."""
        anno = int(data.get("anno", 2025))
        prior_anno = int(data.get("prior_anno", anno - 1))
        language = str(data.get("language", "it"))
        gwp_set = str(data.get("gwp_set", "AR6"))
        company_name = str(data.get("company_name", ""))
        generated_at = str(
            data.get("generated_at") or datetime.now(UTC).isoformat(timespec="seconds")
        )
        dashboard_id = str(data.get("dashboard_id", EXEC_DASHBOARD_ID))
        dashboard_version = str(data.get("dashboard_version", EXEC_DASHBOARD_VERSION))

        totals_cur: dict[str, Any] = dict(data.get("totals_current") or {})
        totals_pri: dict[str, Any] = dict(data.get("totals_prior") or {})

        # Compute total_lb if not supplied
        if totals_cur.get("total_lb") is None:
            s1 = float(totals_cur.get("scope1") or 0)
            s2 = float(totals_cur.get("scope2_lb") or 0)
            s3 = float(totals_cur.get("scope3") or 0)
            totals_cur["total_lb"] = s1 + s2 + s3
        if totals_pri.get("total_lb") is None:
            s1 = float(totals_pri.get("scope1") or 0)
            s2 = float(totals_pri.get("scope2_lb") or 0)
            s3 = float(totals_pri.get("scope3") or 0)
            totals_pri["total_lb"] = s1 + s2 + s3

        # Ensure biogenic_memo key exists
        totals_cur.setdefault("biogenic_memo", None)

        # KPI deltas
        delta_keys = ("scope1", "scope2_lb", "scope2_mb", "scope3", "total_lb")
        deltas: dict[str, Any] = {}
        for k in delta_keys:
            cur_v = totals_cur.get(k)
            pri_v = totals_pri.get(k)
            cur_f = float(cur_v) if cur_v is not None else None
            pri_f = float(pri_v) if pri_v is not None else None
            deltas[k] = _pct_delta(cur_f, pri_f)

        # Intensity deltas
        int_rev_cur = data.get("intensity_revenue")
        int_rev_pri = data.get("intensity_revenue_prior")
        int_m2_cur = data.get("intensity_m2")
        int_m2_pri = data.get("intensity_m2_prior")

        intensity_deltas: dict[str, Any] = {
            "revenue": _pct_delta(
                float(int_rev_cur) if int_rev_cur is not None else None,
                float(int_rev_pri) if int_rev_pri is not None else None,
            ),
            "m2": _pct_delta(
                float(int_m2_cur) if int_m2_cur is not None else None,
                float(int_m2_pri) if int_m2_pri is not None else None,
            ),
        }

        # Bar chart
        try:
            png = _build_chart_png(totals_cur, totals_pri, anno, prior_anno)
            chart_data_uri = _png_to_data_uri(png)
        except Exception:  # noqa: BLE001
            logger.warning("exec_dashboard_chart_failed", exc_info=True)
            chart_data_uri = ""

        # Target (optional)
        target: dict[str, Any] | None = data.get("target") or None

        # Top scope 3 categories (max 5)
        raw_s3 = list(data.get("top_scope3_categories") or [])
        top_scope3 = raw_s3[:5]

        # DQ summary with defaults
        dq_raw: dict[str, Any] = dict(data.get("dq_summary") or {})
        dq_summary = {
            "crit_open": int(dq_raw.get("crit_open", 0) or 0),
            "warn_open": int(dq_raw.get("warn_open", 0) or 0),
            "total_findings": int(dq_raw.get("total_findings", 0) or 0),
        }

        assurance_status = str(data.get("assurance_status", "none")).lower()
        signed_by = data.get("signed_by_esg_manager") or None

        # Derive factor_sources from supplied factor list (option a) or
        # fall back to the value supplied directly in data (option b/c).
        _raw_factors: list[dict[str, Any]] = list(data.get("factors") or [])
        if _raw_factors:
            _pub_sources = sorted({
                f.get("source", "")
                for f in _raw_factors
                if f.get("is_published") and f.get("source")
            })
            factor_sources = " · ".join(_pub_sources) if _pub_sources else "Vedi catalogo fattori"
        else:
            factor_sources = str(data.get("factor_sources") or "Vedi catalogo fattori")

        ctx: dict[str, Any] = {
            "anno": anno,
            "prior_anno": prior_anno,
            "language": language,
            "gwp_set": gwp_set,
            "company_name": company_name,
            "generated_at": generated_at,
            "dashboard_id": dashboard_id,
            "dashboard_version": dashboard_version,
            "totals_current": totals_cur,
            "totals_prior": totals_pri,
            "deltas": deltas,
            "intensity_revenue": int_rev_cur,
            "intensity_m2": int_m2_cur,
            "intensity_deltas": intensity_deltas,
            "chart_data_uri": chart_data_uri,
            "target": target,
            "top_scope3_categories": top_scope3,
            "dq_summary": dq_summary,
            "assurance_status": assurance_status,
            "signed_by_esg_manager": signed_by,
            "factor_sources": factor_sources,
            "css_path": str(_CSS_PATH),
        }
        ctx.update(_labels(language))
        return ctx

    # ------------------------------------------------------------------

    def _render_html(self, ctx: dict[str, Any]) -> str:
        """Render HTML via Jinja2, falling back to a minimal stub."""
        if self._jinja_env is not None:
            try:
                template = self._jinja_env.get_template("exec_dashboard.html")
                return str(template.render(**ctx))
            except Exception:  # noqa: BLE001
                logger.warning("exec_dashboard_template_failed", exc_info=True)
        return _fallback_html_exec(ctx)

    # ------------------------------------------------------------------

    def render_html_only(self, data: dict[str, Any]) -> str:
        """Return rendered HTML string without invoking WeasyPrint.

        Useful for previewing and unit tests that do not require WeasyPrint.
        """
        ctx = self._build_context(data)
        return self._render_html(ctx)

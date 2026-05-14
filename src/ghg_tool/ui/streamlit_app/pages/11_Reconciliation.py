"""Reconciliation page -- CSRD Article 23 / ESRS 2 BP-2 restatement diff.

Lets users:
  1. List the report snapshots for the active year.
  2. Run a diff between a chosen snapshot and the current consolidated state.
  3. Inspect totals, per-row deltas, top-10 contributors, cause breakdown.
  4. (esg_manager only) freeze a new snapshot.
  5. (esg_manager only) jump to the correction workflow with a pre-filled
     restatement justification.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd
import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    DASHBOARD_ID,
    DASHBOARD_VERSION,
    PRODUCT_NAME,
    page_icon,
)

st.set_page_config(
    page_title=f"Riconciliazione · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.brand import (  # noqa: E402
    apply_brand_chrome,
    render_context_bar,
    render_role_chip,
)
from ghg_tool.ui.streamlit_app.lib.filters import available_years  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402

apply_brand_chrome()
require_auth()
lang = get_lang()


# ---------------------------------------------------------------------------
# Local HTTP helpers (the existing api_client caches everything for 5 min
# which is wrong for snapshots that update on user actions).
# ---------------------------------------------------------------------------
_API_BASE = os.environ.get("GHG_API_BASE_URL", "http://localhost:8000")
_TIMEOUT = 30.0

# Okabe-Ito accessible palette (deuteranopia-safe).
_OK_VERMILION = "#D55E00"
_OK_BLUE = "#0072B2"
_OK_GREY = "#999999"


def _headers() -> dict[str, str]:
    from ghg_tool.ui.streamlit_app.lib.auth import _DEMO_MODE, _DEMO_TOKEN

    token = st.session_state.get("token") or (_DEMO_TOKEN if _DEMO_MODE else None)
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _api_get(path: str, params: dict[str, Any] | None = None) -> Any:
    try:
        r = httpx.get(
            f"{_API_BASE}{path}",
            headers=_headers(),
            params=params,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        return {"error": str(exc)}


def _api_post(path: str, body: dict[str, Any]) -> Any:
    try:
        r = httpx.post(
            f"{_API_BASE}{path}",
            headers=_headers(),
            json=body,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as exc:
        return {"error": str(exc), "status_code": exc.response.status_code}
    except httpx.RequestError as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.title(_("nav_reconciliation", lang))

with st.sidebar:
    _years = available_years() or [2024, 2025]
    year_choice = st.selectbox(_("year_filter", lang), [str(y) for y in _years])
    anno = int(year_choice)

render_role_chip(st.session_state.get("role"), lang)
render_context_bar(
    lang=lang,
    year=anno,
    gwp=None,
    role=st.session_state.get("role"),
)

role = st.session_state.get("role") or ""

# ---------------------------------------------------------------------------
# Section 1: list snapshots
# ---------------------------------------------------------------------------
st.subheader(_("recon_snapshots_list", lang))
snapshots = _api_get("/api/v1/reconciliation/snapshots", params={"anno": anno})
if isinstance(snapshots, dict) and "error" in snapshots:
    st.error(f"{_('recon_load_failed', lang)}: {snapshots['error']}")
    snapshots = []

if not snapshots:
    st.info(_("recon_no_snapshots", lang))
else:
    df_snap = pd.DataFrame(snapshots)
    st.dataframe(df_snap, use_container_width=True, hide_index=True)

# Snapshot selector for the diff.
selected_snapshot_id: str | None = None
if snapshots:
    labels = {
        f"{s['taken_at']} | {s['snapshot_kind']} | {s['rows_frozen']} rows": s["id"]
        for s in snapshots
    }
    chosen_label = st.selectbox(_("recon_select_snapshot", lang), [""] + list(labels))
    if chosen_label:
        selected_snapshot_id = labels[chosen_label]

# ---------------------------------------------------------------------------
# Section 2: run diff
# ---------------------------------------------------------------------------
st.divider()
st.subheader(_("recon_run_diff", lang))

diff_result: dict[str, Any] | None = None
if selected_snapshot_id and st.button(_("recon_run_diff_btn", lang), type="primary"):
    with st.spinner(_("loading", lang)):
        diff_result = _api_get(
            "/api/v1/reconciliation/diff",
            params={"anno": anno, "snapshot_id": selected_snapshot_id},
        )
    if isinstance(diff_result, dict) and "error" in diff_result:
        st.error(f"{_('recon_diff_failed', lang)}: {diff_result.get('error')}")
        diff_result = None

# ---------------------------------------------------------------------------
# Section 3: results
# ---------------------------------------------------------------------------
if diff_result:
    st.divider()
    st.subheader(_("recon_results", lang))

    if diff_result.get("restatement_required"):
        st.error(_("recon_restatement_required_banner", lang), icon=":material/warning:")
    else:
        st.success(_("recon_within_threshold", lang))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        _("recon_total_prior", lang),
        f"{float(diff_result['total_prior']):,.2f} tCO2e",
    )
    c2.metric(
        _("recon_total_current", lang),
        f"{float(diff_result['total_current']):,.2f} tCO2e",
    )
    c3.metric(
        _("recon_total_abs_delta", lang),
        f"{float(diff_result['total_abs_delta']):,.2f} tCO2e",
    )
    pct = diff_result.get("total_delta_pct")
    c4.metric(
        _("recon_total_pct_delta", lang),
        f"{float(pct):.2f} %" if pct is not None else "N/A",
    )

    # ----- top-10 deltas (positive / negative bar chart) -----
    rows = diff_result.get("rows", [])
    if rows:
        df = pd.DataFrame(rows)
        df["abs_delta_f"] = df["abs_delta"].astype(float)
        df["abs_delta_magnitude"] = df["abs_delta_f"].abs()
        top10 = df.nlargest(10, "abs_delta_magnitude").copy()
        top10["label"] = (
            "S"
            + top10["scope"].astype(str)
            + " "
            + top10["sub_scope"]
            + " | "
            + top10["codice_sito"].fillna("-")
        )
        top10["color"] = top10["abs_delta_f"].apply(
            lambda v: _OK_VERMILION if v > 0 else _OK_BLUE
        )
        st.markdown(f"### {_('recon_top10_deltas', lang)}")
        try:
            import altair as alt  # noqa: PLC0415

            chart = (
                alt.Chart(top10)
                .mark_bar()
                .encode(
                    x=alt.X("abs_delta_f:Q", title="Delta tCO2e"),
                    y=alt.Y("label:N", sort="-x", title=None),
                    color=alt.Color(
                        "color:N", scale=None, legend=None
                    ),
                    tooltip=["label", "prior_tco2e", "current_tco2e", "cause_category"],
                )
                .properties(height=320)
            )
            st.altair_chart(chart, use_container_width=True)
        except ImportError:
            st.bar_chart(top10.set_index("label")["abs_delta_f"])

        # ----- full deltas dataframe (sorted by magnitude) -----
        st.markdown(f"### {_('recon_all_deltas', lang)}")
        display_cols = [
            "scope",
            "sub_scope",
            "codice_sito",
            "anno",
            "prior_tco2e",
            "current_tco2e",
            "abs_delta",
            "pct_delta",
            "cause_category",
            "material",
        ]
        df_display = df.sort_values("abs_delta_magnitude", ascending=False)[display_cols]
        st.dataframe(df_display, use_container_width=True, hide_index=True)

    # ----- cause breakdown donut -----
    cb = diff_result.get("cause_breakdown") or {}
    cb_df = pd.DataFrame(
        [(k, float(v)) for k, v in cb.items() if float(v) > 0],
        columns=["cause", "abs_delta"],
    )
    if not cb_df.empty:
        st.markdown(f"### {_('recon_cause_breakdown', lang)}")
        try:
            import altair as alt  # noqa: PLC0415

            donut = (
                alt.Chart(cb_df)
                .mark_arc(innerRadius=60)
                .encode(
                    theta="abs_delta:Q",
                    color=alt.Color(
                        "cause:N",
                        scale=alt.Scale(
                            domain=[
                                "factor_update",
                                "data_correction",
                                "methodology",
                                "new_row",
                                "withdrawn_row",
                                "unknown",
                            ],
                            range=[
                                _OK_VERMILION,
                                _OK_BLUE,
                                "#009E73",
                                "#F0E442",
                                "#CC79A7",
                                _OK_GREY,
                            ],
                        ),
                    ),
                    tooltip=["cause", "abs_delta"],
                )
                .properties(height=320)
            )
            st.altair_chart(donut, use_container_width=True)
        except ImportError:
            st.bar_chart(cb_df.set_index("cause"))

    # ----- restatement justification CTA (esg_manager only) -----
    if role == "esg_manager" and diff_result.get("restatement_required"):
        st.divider()
        st.markdown(f"### {_('recon_mark_justification', lang)}")
        with st.form("recon_justification_form"):
            reason_code = st.selectbox(
                _("recon_reason_code", lang),
                [
                    "RESTATEMENT_>5PCT",
                    "FACTOR_UPDATE",
                    "DATA_ERROR",
                    "METHODOLOGY_REVISION",
                    "BOUNDARY_CHANGE",
                ],
            )
            justification = st.text_area(
                _("recon_justification_text", lang), height=120
            )
            submitted = st.form_submit_button(_("recon_submit_justification", lang))
            if submitted:
                # NOTE: This page does NOT submit the correction itself --
                # corrections go through /api/v1/emissions/correction with a
                # specific predecessor row.  We hand off to the Data Entry
                # page with the chosen reason_code pre-set in session_state.
                st.session_state["pending_restatement"] = {
                    "reason_code": reason_code,
                    "justification": justification,
                    "anno": anno,
                    "snapshot_id": selected_snapshot_id,
                }
                st.success(_("recon_justification_recorded", lang))
                st.info(_("recon_go_to_data_entry", lang))

# ---------------------------------------------------------------------------
# Section 4: take new snapshot (esg_manager only)
# ---------------------------------------------------------------------------
if role == "esg_manager":
    st.divider()
    st.subheader(_("recon_take_snapshot", lang))
    with st.form("recon_take_snapshot_form"):
        kind = st.selectbox(
            _("recon_snapshot_kind", lang),
            ["CSRD_FINAL", "EU_ETS_FINAL", "INTERIM"],
        )
        notes = st.text_area(_("recon_snapshot_notes", lang), height=80)
        pdf_sha = st.text_input(
            _("recon_pdf_sha256", lang),
            help=_("recon_pdf_sha256_help", lang),
            max_chars=64,
        )
        submitted = st.form_submit_button(_("recon_freeze_btn", lang), type="primary")
        if submitted:
            body: dict[str, Any] = {"anno": anno, "snapshot_kind": kind}
            if notes:
                body["notes"] = notes
            if pdf_sha and len(pdf_sha) == 64:
                body["pdf_sha256"] = pdf_sha
            res = _api_post("/api/v1/reconciliation/snapshots", body)
            if isinstance(res, dict) and "error" in res:
                st.error(f"{_('recon_snapshot_failed', lang)}: {res.get('error')}")
            else:
                st.success(
                    _("recon_snapshot_created", lang).format(
                        rows=res.get("rows_frozen", 0)
                    )
                )

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    f"{_('footer_factor_source', lang)} | {_('footer_methodology', lang)}"
)

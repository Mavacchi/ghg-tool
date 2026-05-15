"""SBTi Targets page -- ESRS E1-4 science-based reduction targets.

Layout:
  Section 1: Active targets dataframe (all roles).
  Section 2: Per-target trajectory chart + status banner (all roles).
  Section 3: Create target form (esg_manager only; disabled notice for others).
  Section 4: Methodology card with cross-reference to docs/methodology.md.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

import httpx
import pandas as pd
import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    PRODUCT_NAME,
    page_icon,
)

st.set_page_config(
    page_title=f"SBTi Targets · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.brand import (  # noqa: E402
    apply_brand_chrome,
    render_context_bar,
    render_role_chip,
)
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402

apply_brand_chrome()
require_auth()
lang = get_lang()

# ---------------------------------------------------------------------------
# Auth / session helpers
# ---------------------------------------------------------------------------

_API_BASE = os.environ.get("GHG_API_BASE_URL", "http://localhost:8000")
_TIMEOUT = 20.0

_SCOPE_OPTIONS = [
    "S1", "S2_LB", "S2_MB", "S3",
    "S1+S2_LB", "S1+S2_MB", "S1+S2_MB+S3",
]
_ALIGNMENT_OPTIONS = ["1.5C", "WB2C", "2C"]
_METHODOLOGY_OPTIONS = [
    "SBTi_ACA", "SDA", "GEVA", "SBTi_NetZero", "supplier_engagement", "custom",
]
_SBTI_STATUS_OPTIONS = ["none", "committed", "targets_set", "validated"]

_STATUS_ICON: dict[str, str] = {
    "ON_TRACK": "green",
    "SLIGHTLY_OFF": "orange",
    "OFF_TRACK": "red",
    "NO_DATA": "grey",
}

_STATUS_EMOJI: dict[str, str] = {
    "ON_TRACK": "OK",
    "SLIGHTLY_OFF": "~",
    "OFF_TRACK": "X",
    "NO_DATA": "?",
}


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
    except httpx.HTTPStatusError as exc:
        st.error(f"API error {exc.response.status_code}: {exc.response.text[:200]}")
        return None
    except Exception as exc:
        st.error(f"Connection error: {exc}")
        return None


def _api_post(path: str, body: dict[str, Any]) -> tuple[int, Any]:
    try:
        r = httpx.post(
            f"{_API_BASE}{path}",
            headers=_headers(),
            json=body,
            timeout=_TIMEOUT,
        )
        return r.status_code, r.json()
    except Exception as exc:
        return 0, {"detail": str(exc)}


def _api_patch(path: str) -> tuple[int, Any]:
    try:
        r = httpx.patch(
            f"{_API_BASE}{path}",
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        return r.status_code, r.json()
    except Exception as exc:
        return 0, {"detail": str(exc)}


# ---------------------------------------------------------------------------
# Role helpers
# ---------------------------------------------------------------------------

def _user_role() -> str:
    """Extract the role from session state."""
    payload = st.session_state.get("token_payload", {})
    return str(payload.get("role", ""))


def _is_esg_manager() -> bool:
    return _user_role() == "esg_manager"


# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

render_role_chip()
render_context_bar()

st.title(_("sbti_page_title"))
st.caption(_("sbti_page_subtitle"))

# ---------------------------------------------------------------------------
# Section 1: Active targets table
# ---------------------------------------------------------------------------

st.subheader(_("sbti_section_targets"))

targets_data = _api_get("/api/v1/sbti/targets")

if targets_data is None or len(targets_data) == 0:
    st.info(_("sbti_no_targets"))
    targets = []
else:
    targets = targets_data

if targets:
    rows = []
    for t in targets:
        rows.append(
            {
                _("sbti_col_name"): t["name"],
                _("sbti_col_scope"): t["scope_coverage"],
                _("sbti_col_baseline"): t["baseline_year"],
                _("sbti_col_target_year"): t["target_year"],
                _("sbti_col_reduction_pct"): f"{float(t['reduction_pct']):.1f} %",
                _("sbti_col_alignment"): t["alignment"],
                _("sbti_col_approval_status"): t["sbti_approval_status"],
                _("sbti_col_status"): _STATUS_EMOJI.get("NO_DATA", "?"),
                "_target_id": t["target_id"],
            }
        )
    df = pd.DataFrame(rows)
    display_cols = [c for c in df.columns if not c.startswith("_")]
    st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Section 2: Trajectory chart
# ---------------------------------------------------------------------------

st.subheader(_("sbti_section_trajectory"))

if targets:
    try:
        import plotly.graph_objects as go  # type: ignore[import-untyped]
        _PLOTLY = True
    except ImportError:
        _PLOTLY = False

    target_labels = [
        f"{t['name']} ({t['scope_coverage']}, {t['baseline_year']}-{t['target_year']})"
        for t in targets
    ]
    selected_label = st.selectbox(_("sbti_select_target"), target_labels)
    selected_idx = target_labels.index(selected_label)
    selected_target = targets[selected_idx]

    traj_data = _api_get(
        f"/api/v1/sbti/targets/{selected_target['target_id']}/trajectory"
    )

    if traj_data:
        traj_status = traj_data.get("status", "NO_DATA")
        status_key_map = {
            "ON_TRACK": "sbti_status_on_track",
            "SLIGHTLY_OFF": "sbti_status_slightly_off",
            "OFF_TRACK": "sbti_status_off_track",
            "NO_DATA": "sbti_status_no_data",
        }
        status_label = _(status_key_map.get(traj_status, "sbti_status_no_data"))

        if traj_status == "ON_TRACK":
            st.success(f"[{traj_status}] {status_label}")
        elif traj_status == "SLIGHTLY_OFF":
            st.warning(f"[{traj_status}] {status_label}")
        elif traj_status == "OFF_TRACK":
            st.error(f"[{traj_status}] {status_label}")
        else:
            st.info(f"[{traj_status}] {status_label}")

        traj_points = traj_data.get("trajectory", [])
        years = [p["year"] for p in traj_points]
        traj_vals = [float(p["trajectory_tco2e"]) for p in traj_points]
        actual_vals = [
            float(p["actual_tco2e"]) if p["actual_tco2e"] is not None else None
            for p in traj_points
        ]

        if _PLOTLY:
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=years,
                    y=traj_vals,
                    mode="lines+markers",
                    name=_("sbti_trajectory_legend_traj"),
                    line={"color": "#0072B2", "dash": "dash"},
                )
            )
            actual_x = [y for y, v in zip(years, actual_vals, strict=False) if v is not None]
            actual_y = [v for v in actual_vals if v is not None]
            if actual_x:
                fig.add_trace(
                    go.Scatter(
                        x=actual_x,
                        y=actual_y,
                        mode="lines+markers",
                        name=_("sbti_trajectory_legend_actual"),
                        line={"color": "#D55E00"},
                    )
                )
                # Filled delta area between trajectory and actuals.
                common_years = [y for y in actual_x if y in years]
                traj_at_common = [
                    traj_vals[years.index(y)] for y in common_years
                ]
                actual_at_common = [
                    actual_y[actual_x.index(y)] for y in common_years
                ]
                fig.add_trace(
                    go.Scatter(
                        x=common_years + common_years[::-1],
                        y=traj_at_common + actual_at_common[::-1],
                        fill="toself",
                        fillcolor="rgba(213,94,0,0.12)",
                        line={"color": "rgba(255,255,255,0)"},
                        hoverinfo="skip",
                        showlegend=False,
                        name="delta",
                    )
                )
            fig.update_layout(
                xaxis_title="Year",
                yaxis_title="tCO2e",
                height=400,
                margin={"l": 40, "r": 20, "t": 30, "b": 40},
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            # Fallback: simple line chart via st.line_chart.
            chart_df = pd.DataFrame(
                {
                    _("sbti_trajectory_legend_traj"): traj_vals,
                    _("sbti_trajectory_legend_actual"): actual_vals,
                },
                index=years,
            )
            st.line_chart(chart_df)

# ---------------------------------------------------------------------------
# Section 3: Create target form
# ---------------------------------------------------------------------------

st.subheader(_("sbti_section_create"))

if not _is_esg_manager():
    st.info(_("sbti_create_disabled_notice"))
else:
    with st.form("sbti_create_form"):
        name = st.text_input(_("sbti_form_name"))
        scope_coverage = st.selectbox(_("sbti_form_scope"), _SCOPE_OPTIONS)
        col1, col2 = st.columns(2)
        with col1:
            baseline_year = st.number_input(
                _("sbti_form_baseline_year"), min_value=2000, max_value=2099,
                value=2021, step=1,
            )
            baseline_tco2e = st.number_input(
                _("sbti_form_baseline_tco2e"), min_value=0.001, value=10000.0, step=100.0
            )
        with col2:
            target_year = st.number_input(
                _("sbti_form_target_year"), min_value=2001, max_value=2100,
                value=2030, step=1,
            )
            target_tco2e = st.number_input(
                _("sbti_form_target_tco2e"), min_value=0.0, value=5800.0, step=100.0
            )
        alignment = st.selectbox(_("sbti_form_alignment"), _ALIGNMENT_OPTIONS)
        methodology = st.selectbox(_("sbti_form_methodology"), _METHODOLOGY_OPTIONS)
        sbti_approval_status = st.selectbox(
            _("sbti_form_approval_status"), _SBTI_STATUS_OPTIONS
        )
        sbti_validation_date = None
        if sbti_approval_status == "validated":
            sbti_validation_date = st.date_input(_("sbti_form_validation_date"))

        submitted = st.form_submit_button(_("sbti_form_submit"))
        if submitted:
            payload: dict[str, Any] = {
                "name": name,
                "scope_coverage": scope_coverage,
                "baseline_year": int(baseline_year),
                "baseline_tco2e": str(round(Decimal(str(baseline_tco2e)), 3)),
                "target_year": int(target_year),
                "target_tco2e": str(round(Decimal(str(target_tco2e)), 3)),
                "alignment": alignment,
                "methodology": methodology,
                "sbti_approval_status": sbti_approval_status,
                "sbti_validation_date": (
                    sbti_validation_date.isoformat() if sbti_validation_date else None
                ),
            }
            code, resp = _api_post("/api/v1/sbti/targets", payload)
            if code == 201:
                st.success(_("sbti_create_success"))
                st.rerun()
            else:
                detail = resp.get("detail", resp) if isinstance(resp, dict) else resp
                st.error(f"{_('sbti_create_error')} ({code}): {detail}")

# ---------------------------------------------------------------------------
# Section 4: Methodology card
# ---------------------------------------------------------------------------

st.subheader(_("sbti_section_methodology"))
with st.expander(_("sbti_section_methodology"), expanded=False):
    st.markdown(_("sbti_methodology_text"))
    st.markdown(
        "Reference: SBTi Corporate Net-Zero Standard v1.2 (2024) · "
        "ESRS E1-4 AR §34-37 · docs/methodology.md (SBTi section)"
    )

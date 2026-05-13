"""DQ Findings page (FR-32).

Displays OPEN findings + resolution status filter.
Color-codes severity using Okabe-Ito (CRIT = vermilion, WARN = orange).
"Acknowledge" / Waive action calls POST /api/v1/dq-findings/waiver/{id}.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="DQ Findings — GHG", layout="wide")

from ghg_tool.ui.streamlit_app.Home import DASHBOARD_ID, DASHBOARD_VERSION  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.api_client import fetch_dq_findings, post_waiver  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.palette import SEVERITY_COLOURS, STATUS_COLOURS, VERMILION, ORANGE, BLUISH_GREEN  # noqa: E402

require_auth()
lang = get_lang()

st.title(_("nav_dq_findings", lang))

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
with st.sidebar:
    severity_opts = ["Tutti / All", "CRIT", "WARN", "INFO"]
    severity_label = st.selectbox(_("dq_severity", lang), severity_opts)
    severity_filter = None if severity_label.startswith("Tutti") else severity_label

    status_opts = ["Tutti / All", "OPEN", "WAIVED", "REMEDIATED"]
    status_label = st.selectbox(_("dq_status", lang), status_opts)
    status_filter = None if status_label.startswith("Tutti") else status_label

    rule_id_filter = st.text_input(_("dq_rule", lang), value="")

# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------
with st.spinner(_("loading", lang)):
    raw = fetch_dq_findings(
        severity=severity_filter,
        resolution_status=status_filter,
        rule_id=rule_id_filter or None,
        limit=200,
    )

import pandas as pd

if not raw:
    st.info(_("no_data", lang))
else:
    df = pd.DataFrame(raw)

    # Summary metrics
    n_crit = len(df[df["severity"] == "CRIT"]) if "severity" in df.columns else 0
    n_warn = len(df[df["severity"] == "WARN"]) if "severity" in df.columns else 0
    n_open = len(df[df["resolution_status"] == "OPEN"]) if "resolution_status" in df.columns else 0

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(f"CRIT ({_('dq_crit', lang)})", n_crit,
                  help="Colour: Vermilion #D55E00 (Okabe-Ito)")
    with col2:
        st.metric(f"WARN ({_('dq_warn', lang)})", n_warn,
                  help="Colour: Orange #E69F00 (Okabe-Ito)")
    with col3:
        st.metric(f"OPEN", n_open)

    st.divider()

    # Display columns
    display_cols = [
        c for c in [
            "id", "rule_id", "severity", "resolution_status", "scope",
            "codice_sito", "anno", "metric", "value_observed", "value_reference",
            "trigger_desc", "recommended_action", "blocks_pipeline",
            "assessed_at", "resolved_at",
        ] if c in df.columns
    ]

    def _colour_severity(row: pd.Series) -> list[str]:  # type: ignore[type-arg]
        """Colour-code a row by severity.

        Args:
            row: DataFrame row.

        Returns:
            List of CSS style strings for each cell.
        """
        sev = row.get("severity", "")
        color = SEVERITY_COLOURS.get(sev, "")
        if color:
            return [f"background-color: {color}; color: white;"] * len(row)
        return [""] * len(row)

    styled = df[display_cols].style.apply(_colour_severity, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # ---------------------------------------------------------------------------
    # Waiver / acknowledge action (esg_manager only)
    # ---------------------------------------------------------------------------
    role = st.session_state.get("role", "auditor")
    if role == "esg_manager" and "id" in df.columns:
        with st.expander(f"✏️ {_('acknowledge_btn', lang)}", expanded=False):
            finding_ids = df[df["resolution_status"] == "OPEN"]["id"].tolist() \
                if "resolution_status" in df.columns else df["id"].tolist()
            if finding_ids:
                selected_finding = st.selectbox("Finding ID", finding_ids)
                waiver_reason = st.selectbox(
                    "Motivo rinuncia",
                    ["OPERATIONAL_ANNOTATION", "USER_CONFIRMED_ZERO",
                     "METHODOLOGY_INFO", "ASSURANCE_ACCEPTED"],
                )
                waiver_justification = st.text_area(
                    _("correction_justification", lang), min_chars=10
                )
                if st.button(_("acknowledge_btn", lang)):
                    if len(waiver_justification) >= 10:
                        result = post_waiver(
                            finding_id=str(selected_finding),
                            reason_code=waiver_reason,
                            justification=waiver_justification,
                        )
                        if "error" in result:
                            st.error(f"Errore: {result['error']}")
                        else:
                            st.success("Rinuncia applicata.")
                            st.cache_data.clear()
                    else:
                        st.error("Giustificazione deve essere almeno 10 caratteri.")
            else:
                st.info("Nessun finding OPEN disponibile.")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    f"{_('footer_factor_source', lang)} | {_('footer_methodology', lang)}"
)

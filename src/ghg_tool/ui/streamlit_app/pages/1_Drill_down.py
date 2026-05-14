"""Drill-down page — per-site / per-scope / per-year table + bar charts (FR-23).

Features:
  - Stacked bar chart (Plotly) by site × scope × year
  - Filters: year, scope (1/2/3), sub_scope, site (multi-select)
  - Tooltip exposes: factor_source, factor_version, gwp_set, methodology,
    regulatory_stream, confidence_interval_lower/upper
  - Table view (st.dataframe) with same data + CSV download
  - Emission correction form for esg_manager role (FR-21)
  - Okabe-Ito palette throughout
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Drill-down — GHG", layout="wide")

from ghg_tool.ui.streamlit_app.lib.constants import DASHBOARD_ID, DASHBOARD_VERSION  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.banner import render_viano_banner, should_show_viano_banner  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.api_client import (  # noqa: E402
    fetch_emissions,
    emissions_to_dataframe,
    post_correction,
)
from ghg_tool.ui.streamlit_app.lib.palette import plotly_qualitative, SCOPE_COLOURS  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.tooltips import build_emission_hovertemplate, CUSTOMDATA_COLS_WITH_CI  # noqa: E402

require_auth()
lang = get_lang()

st.title(_("nav_drilldown", lang))

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Filtri / Filters")

    year_opts = list(range(2024, 2027))
    selected_year = st.selectbox(_("year_filter", lang), year_opts, index=0)

    scope_opts = [_("all_scopes", lang), "Scope 1", "Scope 2", "Scope 3"]
    selected_scope_label = st.selectbox(_("scope_filter", lang), scope_opts)
    selected_scope: int | None = None
    if selected_scope_label != _("all_scopes", lang):
        selected_scope = int(selected_scope_label.split()[-1])

    all_sites = ["IANO", "VIANO", "VIANO_GARGOLA", "CASALGRANDE",
                 "FIORANO", "SASSUOLO", "FRASSINORO"]
    selected_sites = st.multiselect(
        _("site_filter", lang), all_sites, default=all_sites
    )

    selected_sub_scope = st.text_input(_("sub_scope_filter", lang), value="")

    gwp_set = st.selectbox("GWP Set", ["AR6", "AR5"])

# ---------------------------------------------------------------------------
# VIANO banner
# ---------------------------------------------------------------------------
if should_show_viano_banner(selected_year, selected_sites):
    render_viano_banner(lang)

# ---------------------------------------------------------------------------
# Data fetch + reshape
# ---------------------------------------------------------------------------
with st.spinner(_("loading", lang)):
    raw = fetch_emissions(
        scope=selected_scope,
        anno=selected_year,
        sub_scope=selected_sub_scope or None,
        gwp_set=gwp_set,
        limit=500,
    )

import pandas as pd
import plotly.express as px

df = emissions_to_dataframe(raw)

if df.empty:
    st.info(_("no_data", lang))
else:
    # Apply site filter client-side (API doesn't support multi-site in one call)
    if "codice_sito" in df.columns and selected_sites:
        df = df[df["codice_sito"].isin(selected_sites)]

    # Ensure provenance columns exist
    for col in ["factor_source", "factor_version", "gwp_set", "methodology",
                "regulatory_stream", "co2_biogenic_tonne", "co2_fossil_tonne"]:
        if col not in df.columns:
            df[col] = "N/A" if col not in ("co2_biogenic_tonne", "co2_fossil_tonne") else 0.0

    # Warn if filter excludes material data
    if df.empty:
        st.warning(_("filter_warn_material", lang))
    else:
        # -----------------------------------------------------------------------
        # Stacked bar chart
        # -----------------------------------------------------------------------
        fig = px.bar(
            df,
            x="codice_sito",
            y="tco2e",
            color="sub_scope",
            facet_col="scope" if "scope" in df.columns else None,
            title=f"{_('chart_title_stacked', lang)} — {selected_year}",
            labels={
                "tco2e": "tCO2e",
                "codice_sito": _("table_site", lang),
                "sub_scope": _("table_sub_scope", lang),
            },
            color_discrete_sequence=plotly_qualitative(),
            custom_data=CUSTOMDATA_COLS_WITH_CI
            if all(c in df.columns for c in CUSTOMDATA_COLS_WITH_CI)
            else [c for c in CUSTOMDATA_COLS_WITH_CI if c in df.columns],
        )
        fig.update_traces(
            hovertemplate=build_emission_hovertemplate(include_ci=False, mode="bar")
        )
        fig.update_layout(barmode="stack", legend_title_text=_("table_sub_scope", lang))
        st.plotly_chart(fig, use_container_width=True)

        # -----------------------------------------------------------------------
        # Data table
        # -----------------------------------------------------------------------
        display_cols = [
            c for c in [
                "codice_sito", "anno", "scope", "sub_scope", "tco2e",
                "factor_source", "factor_version", "gwp_set", "methodology",
                "regulatory_stream", "calc_timestamp", "valid_from",
            ] if c in df.columns
        ]
        st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

        # CSV download — defang Excel formula injection in string columns
        from ghg_tool.ui.excel.sheets import _safe_cell_value  # noqa: PLC0415

        _csv_df = df[display_cols].copy()
        for _col in _csv_df.select_dtypes(include=["object"]).columns:
            _csv_df[_col] = _csv_df[_col].map(_safe_cell_value)
        csv_data = _csv_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label=_("download_csv", lang),
            data=csv_data,
            file_name=f"ghg_emissions_{selected_year}_scope{selected_scope or 'all'}.csv",
            mime="text/csv",
        )

        # -----------------------------------------------------------------------
        # Emission correction (esg_manager only, FR-21)
        # -----------------------------------------------------------------------
        role = st.session_state.get("role", "auditor")
        if role == "esg_manager":
            with st.expander(f"✏️ {_('correction_btn', lang)}", expanded=False):
                emission_ids = df["id"].tolist() if "id" in df.columns else []
                if emission_ids:
                    selected_id = st.selectbox("Emission ID da correggere", emission_ids)
                    reason = st.selectbox(
                        _("correction_reason", lang),
                        ["DATA_ERROR", "FACTOR_UPDATE", "BOUNDARY_CHANGE",
                         "METHODOLOGY_REVISION", "RESTATEMENT_>5PCT"],
                    )
                    justification = st.text_area(
                        _("correction_justification", lang),
                        max_chars=4000,
                        help="Minimo 10 caratteri",
                    )
                    tco2e_new = st.number_input("Nuovo valore tCO2e", min_value=0.0, step=0.001)

                    if st.button(_("correction_btn", lang)):
                        if len(justification) >= 10:
                            # Build minimal new_record from the selected row
                            row_dict = df[df["id"] == selected_id].iloc[0].to_dict()
                            new_record: dict[str, object] = {
                                "scope": row_dict.get("scope", 1),
                                "sub_scope": row_dict.get("sub_scope", "combustion"),
                                "codice_sito": row_dict.get("codice_sito"),
                                "anno": row_dict.get("anno", selected_year),
                                "tco2e": tco2e_new,
                                "factor_id": str(row_dict.get("factor_id", "")),
                                "factor_version": str(row_dict.get("factor_version", "1")),
                                "factor_source": str(row_dict.get("factor_source", "DEFRA")),
                                "gwp_set": gwp_set,
                                "methodology": str(row_dict.get("methodology", "activity-based")),
                                "raw_scope": row_dict.get("scope", 1),
                            }
                            result = post_correction(
                                supersedes_id=str(selected_id),
                                new_record=new_record,
                                reason_code=reason,
                                justification=justification,
                            )
                            if "error" in result:
                                st.error(f"{_('correction_err', lang)}: {result['error']}")
                            else:
                                st.success(_("correction_ok", lang))
                        else:
                            st.error("Giustificazione deve essere almeno 10 caratteri.")
                else:
                    st.info("Nessuna emissione disponibile per correzione.")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    f"GWP set: {gwp_set} | {_('footer_factor_source', lang)} | "
    f"{_('footer_methodology', lang)}"
)

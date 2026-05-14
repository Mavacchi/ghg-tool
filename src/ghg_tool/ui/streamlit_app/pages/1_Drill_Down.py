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

from ghg_tool.ui.streamlit_app.lib.constants import (
    DASHBOARD_ID, DASHBOARD_VERSION, KNOWN_SITES, PRODUCT_NAME, page_icon,
)

st.set_page_config(
    page_title=f"Drill-down · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.banner import render_viano_banner, should_show_viano_banner  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.brand import apply_brand_chrome, render_context_bar, render_role_chip  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.filters import sidebar_gwp_filter, sidebar_year_filter  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.help import _help  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.i18n import _  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.api_client import (  # noqa: E402
    fetch_emissions,
    emissions_to_dataframe,
    post_correction,
)
from ghg_tool.ui.streamlit_app.lib.palette import plotly_qualitative, SCOPE_COLOURS  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.tooltips import build_emission_hovertemplate, CUSTOMDATA_COLS_WITH_CI  # noqa: E402

apply_brand_chrome()
require_auth()
lang = get_lang()


def _render_hotspot_tab(
    *,
    lang: str,
    year: int,
    gwp_set: str,
    selected_sites: list[str],
) -> None:
    """Render the Scope 3 hot-spot Pareto tab.

    Pulls current-year and prior-year Scope 3 emissions, runs the pure
    hot-spot service and renders:
      - a Pareto bar+line chart (bars=tco2e, line=cumulative %),
      - a table with rank, category_label, tco2e, %, cumulative %, YoY,
      - a concentration banner when the top-5 carries > 80% of Scope 3,
      - a vermilion outlier-flag column for entries flagged as outliers.
    """
    import uuid as _uuid
    from datetime import UTC as _UTC, datetime as _dt
    from decimal import Decimal as _D

    import pandas as _pd
    import plotly.graph_objects as _go

    from ghg_tool.application.services.hotspot_service import compute_hotspots
    from ghg_tool.domain.entities.emission_record import EmissionRecord
    from ghg_tool.ui.streamlit_app.lib.palette import OKABE_ITO

    def _to_records(rows: list[dict]) -> list[EmissionRecord]:
        records: list[EmissionRecord] = []
        for r in rows:
            if int(r.get("scope", 0)) != 3:
                continue
            try:
                records.append(EmissionRecord(
                    correlation_id=_uuid.uuid4(),
                    raw_row_id=None,
                    scope=3,
                    sub_scope=str(r.get("sub_scope")),
                    codice_sito=r.get("codice_sito"),
                    anno=int(r.get("anno", year)),
                    tco2e=_D(str(r.get("tco2e", "0"))),
                    factor_id=str(r.get("factor_id", "X")),
                    factor_version=str(r.get("factor_version", "1")),
                    factor_source=str(r.get("factor_source", "DEFRA")),
                    gwp_set=str(r.get("gwp_set", gwp_set)),
                    methodology=str(r.get("methodology", "activity-based")),
                    regulatory_stream=str(r.get("regulatory_stream", "CSRD_ESRS_E1")),
                    calc_timestamp=_dt.now(_UTC),
                    created_by="hotspot_view",
                ))
            except Exception:  # noqa: BLE001 - skip malformed rows; never crash the UI
                continue
        return records

    raw_curr = fetch_emissions(scope=3, anno=year, gwp_set=gwp_set, limit=500)
    raw_prev = fetch_emissions(scope=3, anno=year - 1, gwp_set=gwp_set, limit=500)

    if selected_sites:
        raw_curr = [r for r in raw_curr if not r.get("codice_sito") or r.get("codice_sito") in selected_sites]
        raw_prev = [r for r in raw_prev if not r.get("codice_sito") or r.get("codice_sito") in selected_sites]

    entries = compute_hotspots(
        emissions_current=_to_records(raw_curr),
        emissions_prior=_to_records(raw_prev),
        top_n=10,
    )

    if not entries:
        st.info(_("hotspot_no_data", lang))
        return

    # Concentration banner.
    if entries[0].flag_high_concentration:
        st.warning(_("hotspot_high_concentration", lang))
    else:
        st.success(_("hotspot_low_concentration", lang))

    # Pareto chart: bars = tco2e descending, line = cumulative %.
    labels = [e.category_label for e in entries]
    bar_color = OKABE_ITO[2] if len(OKABE_ITO) > 2 else "#0072B2"
    line_color = OKABE_ITO[1] if len(OKABE_ITO) > 1 else "#E69F00"

    fig = _go.Figure()
    fig.add_bar(
        x=labels,
        y=[float(e.tco2e) for e in entries],
        name="tCO2e",
        marker_color=bar_color,
    )
    fig.add_scatter(
        x=labels,
        y=[float(e.cumulative_pct) for e in entries],
        name=_("hotspot_table_cumulative", lang),
        yaxis="y2",
        mode="lines+markers",
        line={"color": line_color, "width": 3},
    )
    fig.update_layout(
        title=f"{_('hotspot_tab_title', lang)} · {year}",
        yaxis={"title": "tCO2e"},
        yaxis2={
            "title": _("hotspot_table_cumulative", lang),
            "overlaying": "y",
            "side": "right",
            "range": [0, 105],
        },
        xaxis={"tickangle": -30},
        legend={"orientation": "h", "y": 1.1},
    )
    st.plotly_chart(fig, use_container_width=True)

    # Table.
    flag_marker_outlier = "⚠️"
    flag_marker_ok = ""
    table_df = _pd.DataFrame([
        {
            _("hotspot_table_rank", lang): e.rank,
            _("hotspot_table_category", lang): e.category_label,
            "tCO2e": float(e.tco2e),
            _("hotspot_table_pct", lang): float(e.pct_of_scope3),
            _("hotspot_table_cumulative", lang): float(e.cumulative_pct),
            _("hotspot_table_yoy", lang): (
                float(e.yoy_delta_pct) if e.yoy_delta_pct is not None else None
            ),
            _("hotspot_table_flag", lang): (
                flag_marker_outlier if e.flag_yoy_outlier else flag_marker_ok
            ),
        }
        for e in entries
    ])

    # Vermilion border-left on outlier rows via pandas Styler.
    def _row_style(row: _pd.Series) -> list[str]:
        flag_col = _("hotspot_table_flag", lang)
        if row.get(flag_col) == flag_marker_outlier:
            return ["border-left: 4px solid #D55E00"] * len(row)
        return [""] * len(row)

    try:
        styled = table_df.style.apply(_row_style, axis=1).format({
            "tCO2e": "{:,.2f}",
            _("hotspot_table_pct", lang): "{:.2f}",
            _("hotspot_table_cumulative", lang): "{:.2f}",
            _("hotspot_table_yoy", lang): lambda v: "-" if v is None else f"{v:+.2f}",
        })
        st.dataframe(styled, use_container_width=True, hide_index=True)
    except Exception:  # noqa: BLE001 - fall back if Styler unsupported
        st.dataframe(table_df, use_container_width=True, hide_index=True)

st.title(_("nav_drilldown", lang))

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Filtri / Filters")

    selected_year = sidebar_year_filter(lang)

    scope_opts = [_("all_scopes", lang), "Scope 1", "Scope 2", "Scope 3"]
    # Drill-through hint from Home: if the user clicked "Esamina" under
    # a specific scope metric, pre-select that scope on first render.
    _hint = st.session_state.pop("drilldown_scope_hint", None)
    _default_idx = 0
    if _hint in (1, 2, 3):
        _default_idx = int(_hint)
    selected_scope_label = st.selectbox(
        _("scope_filter", lang), scope_opts, index=_default_idx,
        help=_help("scope1", lang),
    )
    selected_scope: int | None = None
    if selected_scope_label != _("all_scopes", lang):
        selected_scope = int(selected_scope_label.split()[-1])

    all_sites = list(KNOWN_SITES)
    selected_sites = st.multiselect(
        _("site_filter", lang), all_sites, default=all_sites,
        help=_help("codice_sito", lang),
    )

    selected_sub_scope = st.text_input(_("sub_scope_filter", lang), value="")

    gwp_set = sidebar_gwp_filter(lang)

render_role_chip(st.session_state.get("role"), lang)

render_context_bar(
    lang=lang,
    year=selected_year,
    gwp=gwp_set,
    role=st.session_state.get("role"),
)

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
        _tab_chart, _tab_table, _tab_hotspot = st.tabs([
            f"📊 {_('chart_title_stacked', lang)}",
            f"📋 {_('table_view', lang)}",
            f"🔥 {_('hotspot_tab_title', lang)}",
        ])

        with _tab_chart:
            # -----------------------------------------------------------------------
            # Stacked bar chart
            # -----------------------------------------------------------------------
            fig = px.bar(
                df,
                x="codice_sito",
                y="tco2e",
                color="sub_scope",
                facet_col="scope" if "scope" in df.columns else None,
                title=f"{_('chart_title_stacked', lang)} · {selected_year}",
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

        with _tab_table:
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

            # CSV download (defang Excel formula injection in string columns)
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

        with _tab_hotspot:
            _render_hotspot_tab(
                lang=lang,
                year=selected_year,
                gwp_set=gwp_set,
                selected_sites=selected_sites,
            )

        # -----------------------------------------------------------------------
        # Emission correction (esg_manager only, FR-21)
        # -----------------------------------------------------------------------
        role = st.session_state.get("role", "auditor")
        if role == "esg_manager":
            with st.expander(f"✏️ {_('correction_btn', lang)}", expanded=False):
                emission_ids = df["id"].tolist() if "id" in df.columns else []
                if emission_ids:
                    selected_id = st.selectbox(
                        "Emission ID da correggere", emission_ids,
                        help=_help("audit_predecessor", lang),
                    )
                    reason = st.selectbox(
                        _("correction_reason", lang),
                        ["DATA_ERROR", "FACTOR_UPDATE", "BOUNDARY_CHANGE",
                         "METHODOLOGY_REVISION", "RESTATEMENT_>5PCT"],
                        help=_help("audit_valid_from_to", lang),
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
                            st.error(_("justification_too_short", lang))
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

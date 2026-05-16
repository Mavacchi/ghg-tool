"""Analisi Hot Spot Scope 3 — pagina Streamlit (wave 4).

Consuma ``GET /api/v1/analysis/hotspots?anno=X&top_n=Y`` tramite
``hotspot_client.py`` e visualizza:

  - Tabella Pareto con priority badge colorblind-safe
  - Grafico Plotly (pie o bar, togglabile)
  - Footer con tracciabilità metodologica (GWP set, factor_sources,
    calc_timestamp, metodologia)

RBAC: tutti gli utenti autenticati (``emissions.read``).

Nessun calcolo di emissioni viene eseguito in questa pagina.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import (
    DASHBOARD_ID,
    DASHBOARD_VERSION,
    PRODUCT_NAME,
    page_icon,
)

st.set_page_config(
    page_title=f"Hot Spot Scope 3 · {PRODUCT_NAME}",
    page_icon=page_icon(),
    layout="wide",
)

from ghg_tool.ui.streamlit_app.lib.auth import get_lang, require_auth  # noqa: E402
from ghg_tool.ui.streamlit_app.lib.brand import (  # noqa: E402
    apply_brand_chrome,
    render_context_bar,
    render_role_chip,
)
from ghg_tool.ui.clients.hotspot_client import fetch_hotspots  # noqa: E402

apply_brand_chrome()
require_auth()
lang = get_lang()

# ---------------------------------------------------------------------------
# Colorblind-safe priority palette (Okabe-Ito / ColorBrewer-inspired).
# HIGH  = Okabe-Ito Vermilion  #d62728 (not pure red — deuteranope safe)
# MEDIUM= Okabe-Ito Orange     #ff7f0e (distinct from red and green)
# LOW   = Okabe-Ito Blue-green #2ca02c (adjusted — still distinct from red)
# These are the values specified in the task brief; they are sufficiently
# distinct for the three major forms of color vision deficiency.
# ---------------------------------------------------------------------------
_PRIORITY_COLORS: dict[str, str] = {
    "HIGH": "#d62728",
    "MEDIUM": "#ff7f0e",
    "LOW": "#2ca02c",
}
_PRIORITY_LABELS_IT: dict[str, str] = {
    "HIGH": "Alta",
    "MEDIUM": "Media",
    "LOW": "Bassa",
}


def _priority_badge_html(priority: str) -> str:
    """Return an HTML badge with a colored dot + label for ``priority``.

    Uses both colour AND text label so the badge is not exclusively
    colour-dependent (WCAG 2.1 §1.4.1 — Use of Colour).

    Args:
        priority: One of ``"HIGH"``, ``"MEDIUM"``, ``"LOW"``.

    Returns:
        HTML string with an inline-styled badge.
    """
    import html as _html  # noqa: PLC0415

    color = _PRIORITY_COLORS.get(priority, "#888888")
    # ``priority`` may fall through from a backend-supplied raw value;
    # escape the label before embedding into HTML (CWE-79).
    label = _html.escape(str(_PRIORITY_LABELS_IT.get(priority, priority)))
    return (
        f'<span style="display:inline-flex;align-items:center;gap:4px;">'
        f'<span style="width:10px;height:10px;border-radius:50%;'
        f'background:{color};display:inline-block;" '
        f'aria-label="{label}"></span>'
        f'<span style="font-weight:600;color:{color};">{label}</span>'
        f"</span>"
    )


# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
st.title("Analisi Hot Spot Scope 3")
render_role_chip(st.session_state.get("role"), lang)
render_context_bar(
    lang=lang,
    year=None,
    gwp=None,
    role=st.session_state.get("role"),
)

st.caption(
    "Identifica le categorie Scope 3 a maggiore impatto (analisi Pareto). "
    "Basata su GHG Protocol Scope 3 Standard §10 (hot-spot analysis)."
)

# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------
ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([1, 1, 2])

with ctrl_col1:
    _current_year = dt.date.today().year
    anno = st.selectbox(
        "Anno di riferimento",
        options=list(range(2020, _current_year + 1)),
        index=max(0, _current_year - 2020 - 1),  # default = anno corrente -1
        key="hs_anno",
        help=(
            "Anno fiscale per cui eseguire l'analisi hot-spot. "
            "I dati devono essere stati inseriti dalla pagina Data Entry."
        ),
    )

with ctrl_col2:
    top_n = st.slider(
        "Categorie da mostrare (top N)",
        min_value=3,
        max_value=10,
        value=5,
        step=1,
        key="hs_top_n",
        help="Numero massimo di categorie Scope 3 mostrate nel grafico e nella tabella.",
    )

# Chart type toggle
chart_type = st.radio(
    "Tipo di grafico",
    options=["Barre", "Torta"],
    horizontal=True,
    key="hs_chart_type",
    help="Scegli fra grafico a barre orizzontali (consigliato) o torta.",
)

analizza_btn = st.button(
    "Analizza",
    type="primary",
    key="hs_btn_analizza",
)

# ---------------------------------------------------------------------------
# Fetch and display
# ---------------------------------------------------------------------------

if "hs_last_result" not in st.session_state:
    st.session_state["hs_last_result"] = None

if analizza_btn:
    with st.spinner("Analisi in corso..."):
        result = fetch_hotspots(anno=int(anno), top_n=int(top_n))
    st.session_state["hs_last_result"] = result
    st.session_state["hs_last_anno"] = int(anno)

result = st.session_state.get("hs_last_result")
_anno_used = st.session_state.get("hs_last_anno", int(anno))

if result is None:
    # Empty state — no analysis run yet
    st.info(
        "Seleziona l'anno e il numero di categorie, poi clicca **Analizza**.",
        icon="ℹ️",
    )
else:
    # Error handling
    err = result.get("error")
    if err:
        sc = result.get("status_code")
        if sc == 404:
            st.info(
                f"Nessun dato Scope 3 per l'anno {_anno_used}. "
                "Inserisci dati S3 dalla pagina Data Entry.",
                icon="ℹ️",
            )
        else:
            st.error(
                f"Errore durante l'analisi: {err} "
                f"{'(HTTP ' + str(sc) + ')' if sc else ''}",
                icon="🚫",
            )
    else:
        hotspots = result.get("hotspots", [])
        if not hotspots:
            st.info(
                f"Nessun dato Scope 3 per l'anno {_anno_used}. "
                "Inserisci dati S3 dalla pagina Data Entry.",
                icon="ℹ️",
            )
        else:
            total_tco2e_str = result.get("total_scope3_tco2e", "0")
            try:
                total_tco2e = float(total_tco2e_str)
            except (ValueError, TypeError):
                total_tco2e = 0.0

            flag_conc = result.get("flag_high_concentration", False)
            if flag_conc:
                st.warning(
                    "Le prime 5 categorie superano l'80% del totale Scope 3 "
                    "(alta concentrazione Pareto). Considera di prioritizzare "
                    "interventi su questi fornitori/attività.",
                    icon="⚠️",
                )

            # --- KPI summary ---
            kpi_col1, kpi_col2, kpi_col3 = st.columns(3)
            with kpi_col1:
                st.metric("Totale Scope 3", f"{total_tco2e:,.1f} tCO2e")
            with kpi_col2:
                st.metric("Categorie analizzate", len(hotspots))
            with kpi_col3:
                high_count = sum(
                    1 for h in hotspots if h.get("priority") == "HIGH"
                )
                st.metric("Categorie priorità alta", high_count)

            st.divider()

            # --- Table ---
            st.subheader("Tabella Pareto")

            rows = []
            for h in hotspots:
                try:
                    tco2e_val = float(h.get("tco2e", 0))
                except (ValueError, TypeError):
                    tco2e_val = 0.0
                try:
                    pct_val = float(h.get("pct_of_scope3", 0))
                except (ValueError, TypeError):
                    pct_val = 0.0
                try:
                    cum_pct = float(h.get("cumulative_pct", 0))
                except (ValueError, TypeError):
                    cum_pct = 0.0
                yoy_raw = h.get("yoy_delta_pct")
                yoy_str = (
                    f"{float(yoy_raw):+.1f}%"
                    if yoy_raw is not None
                    else "n.d."
                )
                rows.append({
                    "Rank": h.get("rank", "—"),
                    "Categoria": h.get("category_label", h.get("sub_scope", "—")),
                    "tCO2e": tco2e_val,
                    "% Scope 3": pct_val,
                    "% Cumulata": cum_pct,
                    "YoY": yoy_str,
                    "Priorità": h.get("priority", "—"),
                    "_priority_raw": h.get("priority", ""),
                })

            df_table = pd.DataFrame(rows)

            # Render table with HTML badges for the priority column
            # (st.dataframe does not support HTML; use st.markdown with a
            # manually constructed table for the priority badges).
            # ``Categoria`` and ``YoY`` come from the API (DB-sourced hotspot
            # rows); every cell value is HTML-escaped before interpolation
            # to neutralise XSS via crafted category labels (CWE-79).
            import html as _html_esc  # noqa: PLC0415

            table_html = (
                '<table style="width:100%;border-collapse:collapse;font-size:0.9rem;">'
                "<thead><tr>"
                + "".join(
                    f'<th style="text-align:left;padding:6px 10px;'
                    f'border-bottom:2px solid #ddd;">{col}</th>'
                    for col in [
                        "Rank", "Categoria", "tCO2e", "% Scope 3",
                        "% Cumulata", "YoY", "Priorità",
                    ]
                )
                + "</tr></thead><tbody>"
            )
            for _, row in df_table.iterrows():
                table_html += "<tr>"
                table_html += (
                    f'<td style="padding:6px 10px;">'
                    f'{_html_esc.escape(str(row["Rank"]))}</td>'
                )
                table_html += (
                    f'<td style="padding:6px 10px;">'
                    f'{_html_esc.escape(str(row["Categoria"]))}</td>'
                )
                table_html += (
                    f'<td style="padding:6px 10px;text-align:right;">'
                    f'{row["tCO2e"]:,.1f}</td>'
                )
                table_html += (
                    f'<td style="padding:6px 10px;text-align:right;">'
                    f'{row["% Scope 3"]:.1f}%</td>'
                )
                table_html += (
                    f'<td style="padding:6px 10px;text-align:right;">'
                    f'{row["% Cumulata"]:.1f}%</td>'
                )
                table_html += (
                    f'<td style="padding:6px 10px;text-align:right;">'
                    f'{_html_esc.escape(str(row["YoY"]))}</td>'
                )
                # ``_priority_badge_html`` returns module-static markup keyed by
                # a controlled enum-like priority code; no DB interpolation.
                table_html += (
                    f'<td style="padding:6px 10px;">'
                    f'{_priority_badge_html(row["_priority_raw"])}</td>'
                )
                table_html += "</tr>"
            table_html += "</tbody></table>"
            st.markdown(table_html, unsafe_allow_html=True)

            # CSV download
            df_download = df_table.drop(columns=["_priority_raw"])
            st.download_button(
                label="Scarica CSV",
                data=df_download.to_csv(index=False).encode("utf-8"),
                file_name=f"hotspot_scope3_{_anno_used}.csv",
                mime="text/csv",
                key="hs_dl_csv",
            )

            st.divider()

            # --- Plotly chart ---
            st.subheader("Grafico" + (" — Barre" if chart_type == "Barre" else " — Torta"))

            labels = [h.get("category_label", h.get("sub_scope", "")) for h in hotspots]
            values = []
            for h in hotspots:
                try:
                    values.append(float(h.get("tco2e", 0)))
                except (ValueError, TypeError):
                    values.append(0.0)

            # Colorblind-safe palette: Okabe-Ito qualitative
            _OI_PALETTE = [
                "#0072B2",  # blue
                "#E69F00",  # orange
                "#56B4E9",  # sky blue
                "#009E73",  # bluish green
                "#CC79A7",  # reddish purple
                "#D55E00",  # vermilion
                "#F0E442",  # yellow
                "#000000",  # black
            ]

            if chart_type == "Barre":
                fig = go.Figure(
                    go.Bar(
                        x=values,
                        y=labels,
                        orientation="h",
                        marker_color=[
                            _OI_PALETTE[i % len(_OI_PALETTE)]
                            for i in range(len(labels))
                        ],
                        text=[f"{v:,.1f} tCO2e" for v in values],
                        textposition="outside",
                        hovertemplate=(
                            "<b>%{y}</b><br>"
                            "tCO2e: %{x:,.2f}<br>"
                            "<extra></extra>"
                        ),
                    )
                )
                fig.update_layout(
                    title=f"Top {top_n} Scope 3 — Anno {_anno_used}",
                    xaxis_title="tCO2e",
                    yaxis_title="Categoria",
                    yaxis={"autorange": "reversed"},
                    height=max(350, len(labels) * 50 + 100),
                    margin={"l": 220, "r": 80, "t": 60, "b": 60},
                )
            else:
                fig = go.Figure(
                    go.Pie(
                        labels=labels,
                        values=values,
                        hole=0.35,
                        marker_colors=[
                            _OI_PALETTE[i % len(_OI_PALETTE)]
                            for i in range(len(labels))
                        ],
                        textinfo="label+percent",
                        hovertemplate=(
                            "<b>%{label}</b><br>"
                            "tCO2e: %{value:,.2f}<br>"
                            "% Scope 3: %{percent}<br>"
                            "<extra></extra>"
                        ),
                    )
                )
                fig.update_layout(
                    title=f"Top {top_n} Scope 3 — Anno {_anno_used}",
                    height=420,
                )

            st.plotly_chart(fig, use_container_width=True)

            # --- Metadata footer ---
            st.divider()
            _gwp = result.get("gwp_set", "AR6")
            _sources = result.get("factor_sources") or []
            if isinstance(_sources, list | tuple):
                _sources_str = ", ".join(sorted(_sources)) if _sources else "—"
            else:
                _sources_str = str(_sources)
            _calc_ts = result.get("calc_timestamp", "")
            _methodology = result.get(
                "methodology",
                "GHG Protocol Scope 3 Standard §10 (hot-spot analysis)",
            )

            st.caption(
                f"**Metodologia:** {_methodology} · "
                f"**GWP set:** {_gwp} · "
                f"**Fonti fattore:** {_sources_str} · "
                f"**Calc timestamp:** {_calc_ts}"
            )
            st.caption(
                f"I valori sono per anno {_anno_used}; le altre categorie S3 "
                "sotto la soglia non sono mostrate. "
                "Vedi docs/methodology/factor_sources.md per i SHA-256 dei PDF sorgente."
            )

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Dashboard ID: {DASHBOARD_ID} | v{DASHBOARD_VERSION} | "
    "Analisi hot-spot: GHG Protocol Scope 3 Standard §10."
)

"""Plotly hovertemplate builder with mandatory provenance fields (FR-23).

Every chart tooltip MUST expose:
  - factor_source
  - factor_version
  - gwp_set
  - methodology
  - regulatory_stream  (where available)
  - confidence_interval_lower / upper  (where available)

Never display a numeric emission value without these in scope.
"""

from __future__ import annotations

from typing import Literal


def build_emission_hovertemplate(
    *,
    value_label: str = "tCO2e",
    extra_fields: list[str] | None = None,
    include_ci: bool = False,
    mode: Literal["bar", "scatter", "line"] = "bar",
) -> str:
    """Build a Plotly hovertemplate string for emission charts.

    The template assumes ``customdata`` columns are ordered as:
      [0] factor_source
      [1] factor_version
      [2] gwp_set
      [3] methodology
      [4] regulatory_stream      (optional, only when include_ci=False)
      [4 or 5] ci_lower          (when include_ci=True)
      [5 or 6] ci_upper          (when include_ci=True)

    Args:
        value_label: Label for the primary numeric value.
        extra_fields: Additional display lines (plain text, no customdata).
        include_ci: If True, append CI lower/upper from customdata[4:6].
        mode: Chart type affects the template format slightly.

    Returns:
        Plotly hovertemplate string with ``<extra></extra>`` trailer.
    """
    lines = [
        "<b>%{x}</b>" if mode == "bar" else "<b>%{fullData.name}</b>",
        f"{value_label}: <b>%{{y:,.4f}}</b>",
        "---",
        "Fonte fattore: %{customdata[0]}",
        "Versione: %{customdata[1]}",
        "GWP set: %{customdata[2]}",
        "Metodologia: %{customdata[3]}",
        "Stream: %{customdata[4]}",
    ]

    if include_ci:
        lines += [
            "CI 95% inferiore: %{customdata[5]:,.4f}",
            "CI 95% superiore: %{customdata[6]:,.4f}",
        ]

    if extra_fields:
        lines += extra_fields

    lines.append("<extra></extra>")
    return "<br>".join(lines)


# Standard customdata column names for emissions charts
CUSTOMDATA_COLS: list[str] = [
    "factor_source",
    "factor_version",
    "gwp_set",
    "methodology",
    "regulatory_stream",
]

CUSTOMDATA_COLS_WITH_CI: list[str] = [
    "factor_source",
    "factor_version",
    "gwp_set",
    "methodology",
    "regulatory_stream",
    "ci_lower",
    "ci_upper",
]

"""Calculation modules — wave 2 implementation per architecture.md §8.

Each ``scope*`` module exports a ``calculate`` function that returns a
``list[EmissionRecord]``.  These are pure functions: no DB writes, no
network, no logging side-effects.  The
``application.services.calc_orchestrator`` wires the modules together
and handles persistence via the wave 1 repositories.
"""

from ghg_tool.application.calc import (
    scope1_combustion,
    scope1_fugitive_zero,
    scope1_process,
    scope2_lb,
    scope2_mb,
    scope3_cat1_purchased_goods,
    scope3_cat2_capital_goods,
    scope3_cat3_fuel_energy,
    scope3_cat4_upstream_transport,
    scope3_cat5_waste,
    scope3_cat6_business_travel,
    scope3_cat7_commuting,
    scope3_cat9_downstream_transport,
    scope3_cat11_zero_line,
    scope3_cat12_eol,
    scope3_cat_omitted_zero_lines,
)

__all__ = [
    "scope1_combustion",
    "scope1_fugitive_zero",
    "scope1_process",
    "scope2_lb",
    "scope2_mb",
    "scope3_cat11_zero_line",
    "scope3_cat12_eol",
    "scope3_cat1_purchased_goods",
    "scope3_cat2_capital_goods",
    "scope3_cat3_fuel_energy",
    "scope3_cat4_upstream_transport",
    "scope3_cat5_waste",
    "scope3_cat6_business_travel",
    "scope3_cat7_commuting",
    "scope3_cat9_downstream_transport",
    "scope3_cat_omitted_zero_lines",
]

"""Value object: GWPSet — GWP100 values per IPCC assessment report.

No framework imports.  Pure Python.  Used by calc modules (wave 2) to ensure
GWP values are injected rather than hardcoded, enabling AR5/AR6 swappability
without code changes (FR-19, FR-34, MG-10/12).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

GWPSetCode = Literal["AR6", "AR5"]


@dataclass(frozen=True)
class GWPValues:
    """Immutable GWP100 value set for a specific IPCC assessment report.

    Attributes:
        code: Assessment report code ('AR6' or 'AR5').
        co2: GWP100 for CO2 (always 1).
        ch4: GWP100 for CH4 (fossil aggregate default).
        n2o: GWP100 for N2O.
        sf6: GWP100 for SF6.
        hfc134a: GWP100 for HFC-134a.
    """

    code: GWPSetCode
    co2: Decimal
    ch4: Decimal
    n2o: Decimal
    sf6: Decimal
    hfc134a: Decimal


# Canonical instances — seeded per methodology_validation.md §5.2 / §5.3
AR6 = GWPValues(
    code="AR6",
    co2=Decimal("1"),
    ch4=Decimal("27.9"),    # IPCC AR6 WG1 Ch.7 SM Table 7.SM.7 — aggregate default
    n2o=Decimal("273"),
    sf6=Decimal("25200"),
    hfc134a=Decimal("1530"),
)

AR5 = GWPValues(
    code="AR5",
    co2=Decimal("1"),
    ch4=Decimal("28"),      # IPCC AR5 WG1 Ch.8 Table 8.7 — no climate-carbon feedback
    n2o=Decimal("265"),     # EU ETS 2023/2122 uses AR5
    sf6=Decimal("23500"),
    hfc134a=Decimal("1300"),
)

_REGISTRY: dict[GWPSetCode, GWPValues] = {"AR6": AR6, "AR5": AR5}


def get_gwp_values(code: GWPSetCode) -> GWPValues:
    """Retrieve the canonical GWP value set for a given code.

    Args:
        code: Assessment report code ('AR6' or 'AR5').

    Returns:
        The corresponding ``GWPValues`` instance.

    Raises:
        KeyError: If code is not in {'AR6', 'AR5'}.
    """
    if code not in _REGISTRY:
        raise KeyError(f"Unknown GWP set code: {code!r}. Must be 'AR6' or 'AR5'.")
    return _REGISTRY[code]

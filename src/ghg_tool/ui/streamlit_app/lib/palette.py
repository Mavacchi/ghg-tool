"""Okabe-Ito 8-colour colorblind-safe palette (NFR-22).

All charts, tables, and PDF figures MUST use this palette.
No red/green pairs for status signalling — use:
  - CRIT  -> VERMILION  (#D55E00)
  - WARN  -> ORANGE     (#E69F00)
  - OK    -> BLUISH_GREEN (#009E73)

References:
  Okabe & Ito (2008) "Color Universal Design (CUD) — How to make
  figures and presentations that are friendly to colorblind people"
  https://jfly.uni-koeln.de/color/
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Named colours (Okabe-Ito 8-colour palette)
# ---------------------------------------------------------------------------
BLACK: Final[str] = "#000000"
ORANGE: Final[str] = "#E69F00"
SKY_BLUE: Final[str] = "#56B4E9"
BLUISH_GREEN: Final[str] = "#009E73"
YELLOW: Final[str] = "#F0E442"
BLUE: Final[str] = "#0072B2"
VERMILION: Final[str] = "#D55E00"
REDDISH_PURPLE: Final[str] = "#CC79A7"

# Ordered list for sequential assignment
OKABE_ITO: Final[list[str]] = [
    BLUE,
    ORANGE,
    BLUISH_GREEN,
    VERMILION,
    SKY_BLUE,
    REDDISH_PURPLE,
    YELLOW,
    BLACK,
]

# ---------------------------------------------------------------------------
# Semantic mappings
# ---------------------------------------------------------------------------

# Scope colours — consistent across all charts
SCOPE_COLOURS: Final[dict[int, str]] = {
    1: VERMILION,
    2: BLUE,
    3: BLUISH_GREEN,
}

# Severity colours (DQ findings)
SEVERITY_COLOURS: Final[dict[str, str]] = {
    "CRIT": VERMILION,
    "WARN": ORANGE,
    "INFO": BLUISH_GREEN,
}

# Resolution status colours
STATUS_COLOURS: Final[dict[str, str]] = {
    "OPEN": ORANGE,
    "WAIVED": SKY_BLUE,
    "REMEDIATED": BLUISH_GREEN,
    "RESOLVED": BLUISH_GREEN,
}

# Header fill for Excel (openpyxl ARGB: alpha + RGB)
EXCEL_HEADER_FILL: Final[str] = "FF0072B2"  # BLUE with full alpha


def scope_color(scope: int) -> str:
    """Return the Okabe-Ito colour for a given scope number.

    Args:
        scope: Emission scope (1, 2, or 3).

    Returns:
        Hex colour string.  Falls back to BLACK for unknown scopes.
    """
    return SCOPE_COLOURS.get(scope, BLACK)


def severity_color(severity: str) -> str:
    """Return the Okabe-Ito colour for a DQ finding severity.

    Args:
        severity: One of 'CRIT', 'WARN', 'INFO'.

    Returns:
        Hex colour string.  Falls back to BLACK for unknown values.
    """
    return SEVERITY_COLOURS.get(severity.upper(), BLACK)


def plotly_qualitative() -> list[str]:
    """Return the Okabe-Ito palette as a Plotly-compatible colour sequence.

    Returns:
        List of 8 hex colour strings suitable for
        ``color_discrete_sequence`` in Plotly Express.
    """
    return list(OKABE_ITO)

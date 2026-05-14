"""Streamlit-app constants shared across Home.py and every page.

Lives in ``lib/`` so that pages can import these symbols without
re-executing ``Home.py`` (which would call ``st.set_page_config`` a
second time and crash with ``StreamlitAPIException``).

Branding values default to Gruppo Ceramiche Gresmalt S.p.A. (the
project's launch customer) but can be overridden via environment
variables:

  - ``GHG_PRODUCT_NAME``  — product / software name (default "Carbontrace").
  - ``GHG_COMPANY_NAME``  — display name shown in titles, footers, PDF.
  - ``GHG_COMPANY_SHORT`` — short name for browser tab / page_title.
  - ``GHG_TENANT_ID``     — tenant identifier used by the auth fallback.
  - ``GHG_SITES``         — comma-separated list of site codes (overrides
                            the built-in 7-site default).

The ``BRAND_*`` palette is the *chrome* palette (page background,
sidebar, headings) from the Gresmalt website. **Data-visualisation
colours stay Okabe-Ito** (see ``palette.py``) for colorblind safety
and to preserve the methodology-level mapping (VERMILION=Scope 1,
BLUE=Scope 2, BLUISH_GREEN=Scope 3).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

DASHBOARD_VERSION: Final[str] = "1.0.0"
DASHBOARD_ID: Final[str] = "esg-main-2026"

_DEFAULT_PRODUCT_NAME: Final[str] = "Carbontrace"
_DEFAULT_COMPANY_NAME: Final[str] = "Gruppo Ceramiche Gresmalt S.p.A."
_DEFAULT_COMPANY_SHORT: Final[str] = "Gresmalt"
_DEFAULT_TENANT_ID: Final[str] = "gresmalt-v1"
_DEFAULT_SITES: Final[tuple[str, ...]] = (
    "IANO",
    "VIANO",
    "VIANO_GARGOLA",
    "CASALGRANDE",
    "FIORANO",
    "SASSUOLO",
    "FRASSINORO",
)


def _env(name: str, default: str) -> str:
    """Return env var if non-empty, else ``default``."""
    value = os.getenv(name, "").strip()
    return value if value else default


PRODUCT_NAME: Final[str] = _env("GHG_PRODUCT_NAME", _DEFAULT_PRODUCT_NAME)
COMPANY_NAME: Final[str] = _env("GHG_COMPANY_NAME", _DEFAULT_COMPANY_NAME)
COMPANY_SHORT: Final[str] = _env("GHG_COMPANY_SHORT", _DEFAULT_COMPANY_SHORT)
TENANT_ID: Final[str] = _env("GHG_TENANT_ID", _DEFAULT_TENANT_ID)


def _parse_sites(raw: str) -> tuple[str, ...]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return tuple(parts) if parts else _DEFAULT_SITES


KNOWN_SITES: Final[tuple[str, ...]] = _parse_sites(os.getenv("GHG_SITES", ""))

# ---------------------------------------------------------------------------
# Gresmalt brand chrome palette (sampled from gresmalt.it homepage).
# Applied to: page background, sidebar, headings, body text.
# NOT applied to chart series or status badges (those use Okabe-Ito —
# see ``palette.py`` — for colorblind safety and methodology mapping).
# ---------------------------------------------------------------------------
BRAND_INK: Final[str] = "#202020"       # near-black headings, body type
BRAND_OFF_WHITE: Final[str] = "#F6F6F6"  # page background
BRAND_WARM_BEIGE: Final[str] = "#F0EBE5"  # hero / info panels
BRAND_SAND: Final[str] = "#E9E2D8"        # secondary surfaces, sidebar
BRAND_ACCENT: Final[str] = "#788B99"      # accent (mission section)

# ---------------------------------------------------------------------------
# Brand asset paths (bundled inside the package wheel).
# ---------------------------------------------------------------------------
_ASSETS_DIR: Final[Path] = Path(__file__).parent.parent / "assets"
LOGO_PATH: Final[Path] = _ASSETS_DIR / "logo.png"
FAVICON_PATH: Final[Path] = _ASSETS_DIR / "favicon.png"


def page_icon() -> str:
    """Return the favicon path if bundled, else a Unicode fallback glyph.

    Streamlit's ``page_icon`` accepts a filesystem path or an emoji; using
    a fallback keeps the dashboard launchable even from a partial checkout.
    """
    return str(FAVICON_PATH) if FAVICON_PATH.exists() else "🏭"

"""Streamlit-app constants shared across Home.py and every page.

Lives in ``lib/`` so that pages can import these symbols without
re-executing ``Home.py`` (which would call ``st.set_page_config`` a
second time and crash with ``StreamlitAPIException``).

Branding values default to Saturnia Ceramica (the project's launch tenant)
but can be overridden via environment variables:

  - ``GHG_COMPANY_NAME``  — display name shown in titles, footers, PDF.
  - ``GHG_COMPANY_SHORT`` — short name for browser tab / page_title.
  - ``GHG_TENANT_ID``     — tenant identifier used by the auth fallback.
  - ``GHG_SITES``         — comma-separated list of site codes (overrides
                            the built-in 7-site Saturnia list).
"""

from __future__ import annotations

import os
from typing import Final

DASHBOARD_VERSION: Final[str] = "1.0.0"
DASHBOARD_ID: Final[str] = "esg-main-2026"

_DEFAULT_COMPANY_NAME: Final[str] = "Saturnia Ceramica S.r.l."
_DEFAULT_COMPANY_SHORT: Final[str] = "Saturnia Ceramica"
_DEFAULT_TENANT_ID: Final[str] = "saturnia-ceramica-v1"
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


COMPANY_NAME: Final[str] = _env("GHG_COMPANY_NAME", _DEFAULT_COMPANY_NAME)
COMPANY_SHORT: Final[str] = _env("GHG_COMPANY_SHORT", _DEFAULT_COMPANY_SHORT)
TENANT_ID: Final[str] = _env("GHG_TENANT_ID", _DEFAULT_TENANT_ID)


def _parse_sites(raw: str) -> tuple[str, ...]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return tuple(parts) if parts else _DEFAULT_SITES


KNOWN_SITES: Final[tuple[str, ...]] = _parse_sites(os.getenv("GHG_SITES", ""))

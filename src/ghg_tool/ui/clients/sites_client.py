"""Client for GET /api/v1/sites — site catalogue with M6 fields.

Wraps the ``/api/v1/sites`` endpoint introduced in migration M6.  Returns
``Site`` dataclass instances that include ``site_type`` and ``country`` from
the M6 schema (decision #7 and #2 respectively).

Responsibilities of this module:
  - Deserialise the ``SiteOut`` JSON response into typed ``Site`` objects.
  - Cache the site list with a 5-minute TTL (``@st.cache_data(ttl=300)``).
  - Expose convenience helpers ``get_sites_by_type`` and ``get_site`` for
    the auto-calc form and other UI consumers.
  - Provide a graceful offline fallback (``KNOWN_SITES`` constants) when the
    backend is unreachable, so the UI degrades rather than crashes.

No GHG calculations are performed here.  This module is a pure HTTP consumer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

import httpx
import streamlit as st

from ghg_tool.ui.streamlit_app.lib.constants import KNOWN_SITES

# ---------------------------------------------------------------------------
# Typed domain object (mirrors SiteOut from the API router)
# ---------------------------------------------------------------------------

SiteType = Literal["STABILIMENTO_PRODUTTIVO", "UFFICIO", "MAGAZZINO"]

# Italian labels for each site_type value (UI display only).
SITE_TYPE_LABELS: dict[str, str] = {
    "STABILIMENTO_PRODUTTIVO": "Stabilimento",
    "UFFICIO": "Ufficio",
    "MAGAZZINO": "Magazzino",
}


@dataclass(frozen=True)
class Site:
    """A single active production site (M6 schema).

    Attributes:
        codice_sito: Site code (e.g. ``IANO``, ``VIANO``).
        full_name: Human-readable full name of the site.
        role: Operational role of the site.
        geography: ISO-3166 alpha-2 country code or region tag.
        country: ISO-3166 alpha-2 country code (M6, decision #2).
        site_type: Classification from M6 decision #7.
        eu_ets_installation_id: EU ETS installation identifier; ``None`` if not
            registered.
        is_active: Whether the site is within the current operational boundary.
    """

    codice_sito: str
    full_name: str
    role: str
    geography: str
    country: str
    site_type: SiteType
    eu_ets_installation_id: str | None = None
    is_active: bool = True

    @property
    def site_type_label(self) -> str:
        """Return the Italian display label for this site's type."""
        return SITE_TYPE_LABELS.get(self.site_type, self.site_type)

    @property
    def dropdown_label(self) -> str:
        """Return the dropdown label ``"{codice_sito} — {full_name} ({site_type_label})"``."""
        return f"{self.codice_sito} — {self.full_name} ({self.site_type_label})"


# ---------------------------------------------------------------------------
# Offline fallback: build minimal Site objects from the KNOWN_SITES constant
# so the UI can degrade gracefully when the backend is unreachable.
# ---------------------------------------------------------------------------

def _build_fallback_sites() -> list[Site]:
    """Return stub ``Site`` objects from the ``KNOWN_SITES`` constant.

    These stubs have ``site_type="STABILIMENTO_PRODUTTIVO"`` for all sites
    (conservative default: shows all sub-scope options) and are used ONLY
    when the ``/api/v1/sites`` endpoint is unreachable.  Once the backend
    responds, the cached real data takes over.
    """
    fallback = []
    for code in KNOWN_SITES:
        fallback.append(
            Site(
                codice_sito=code,
                full_name=code,
                role="production",
                geography="IT",
                country="IT",
                site_type="STABILIMENTO_PRODUTTIVO",
            )
        )
    return fallback


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL = os.environ.get("GHG_API_BASE_URL", "http://localhost:8000")
_TIMEOUT = 15.0


def _get_base_url() -> str:
    return st.session_state.get("api_base_url", _DEFAULT_BASE_URL)


def _get_auth_headers() -> dict[str, str]:
    """Build auth headers using the JWT token from session_state."""
    from ghg_tool.ui.streamlit_app.lib.auth import _DEMO_MODE, _DEMO_TOKEN  # noqa: PLC0415

    token = st.session_state.get("token")
    if not token:
        token = _DEMO_TOKEN if _DEMO_MODE else None
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ---------------------------------------------------------------------------
# Cached public API
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300, show_spinner=False)
def get_sites() -> list[Site]:
    """Fetch all active sites from ``GET /api/v1/sites`` (TTL 5 min).

    Deserialises the ``SiteOut`` JSON into ``Site`` dataclass instances,
    including the M6 fields ``site_type`` and ``country``.

    Returns the offline fallback list (all coded as STABILIMENTO_PRODUTTIVO)
    when the backend is unreachable so the form renders in degraded mode
    rather than crashing entirely.

    Returns:
        List of ``Site`` instances for the caller's tenant.
    """
    try:
        resp = httpx.get(
            f"{_get_base_url()}/api/v1/sites/",
            headers=_get_auth_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_sites = data.get("sites", [])
        sites = []
        for raw in raw_sites:
            # Guard: skip rows that are missing M6 fields from older API versions.
            if "site_type" not in raw or "country" not in raw:
                continue
            sites.append(
                Site(
                    codice_sito=raw["codice_sito"],
                    full_name=raw.get("full_name", raw["codice_sito"]),
                    role=raw.get("role", ""),
                    geography=raw.get("geography", raw.get("country", "IT")),
                    country=raw["country"],
                    site_type=raw["site_type"],
                    eu_ets_installation_id=raw.get("eu_ets_installation_id"),
                    is_active=raw.get("is_active", True),
                )
            )
        if sites:
            return sites
        # Empty response: fall through to fallback.
    except (httpx.HTTPStatusError, httpx.RequestError):
        pass
    return _build_fallback_sites()


def get_sites_by_type(site_type: SiteType) -> list[Site]:
    """Return only sites whose ``site_type`` matches ``site_type``.

    Args:
        site_type: One of ``"STABILIMENTO_PRODUTTIVO"``, ``"UFFICIO"``,
            or ``"MAGAZZINO"``.

    Returns:
        Filtered list of ``Site`` instances.
    """
    return [s for s in get_sites() if s.site_type == site_type]


def get_site(codice_sito: str) -> Site | None:
    """Look up a single site by its ``codice_sito``.

    Args:
        codice_sito: Site code (e.g. ``"IANO"``).

    Returns:
        The matching ``Site``, or ``None`` if not found.
    """
    for s in get_sites():
        if s.codice_sito == codice_sito:
            return s
    return None

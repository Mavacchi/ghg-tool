"""Privacy notice helper — GDPR Art. 13 (F-14).

Renders the mandatory Art. 13 information notice at login and registration
surfaces.  The notice text is in Italian (primary audience) and includes all
elements required by Art. 13(1) and 13(2) GDPR:

  - Identity and contact details of the controller (placeholder to be
    substituted per deployment via environment or configuration).
  - Purposes and legal basis for processing.
  - Retention period.
  - Data subject rights (Arts. 15-22).
  - DPO contact (configurable via ``GHG_DPO_EMAIL`` env var).
  - Link to the full privacy policy or ROPA document.

Deployment-specific values (controller name, DPO e-mail) are read from
environment variables so that no code change is needed when the tool is
redeployed for a different legal entity.
"""

from __future__ import annotations

import os
import pathlib

import streamlit as st

# ---------------------------------------------------------------------------
# Deployment-configurable values — set via env vars at deploy time.
# ---------------------------------------------------------------------------

#: Legal name of the data controller.  Override at deployment time via
#: ``GHG_CONTROLLER_NAME`` env var if redeployed for a different legal entity.
_CONTROLLER_NAME: str = os.getenv(
    "GHG_CONTROLLER_NAME",
    "Gruppo Ceramiche Gresmalt S.p.A.",
)

#: E-mail address of the Data Protection Officer.  Override at deployment time
#: via ``GHG_DPO_EMAIL`` env var.
_DPO_EMAIL: str = os.getenv(
    "GHG_DPO_EMAIL",
    "info@gresmalt.it",
)

# ---------------------------------------------------------------------------
# Privacy policy link resolution.
# We prefer /static/privacy.html (if the static file exists at deploy time);
# otherwise we fall back to the GDPR processing register Markdown document.
# ---------------------------------------------------------------------------

_WORKTREE_ROOT = pathlib.Path(__file__).parents[6]
_STATIC_PRIVACY_HTML = _WORKTREE_ROOT / "static" / "privacy.html"


def _privacy_policy_link() -> str | None:
    """Return a clickable Markdown link to the full privacy policy, or None.

    Streamlit does not serve the repo's ``docs/*.md`` tree at any URL, so the
    previous fallback (``docs/gdpr_processing_register.md``) rendered as a
    white page when clicked. We now only emit a link when a deployment-time
    ``static/privacy.html`` is actually present; otherwise we return ``None``
    and the caller omits the link entirely. The full ROPA is still available
    in the repo for auditors; the privacy notice itself in the Streamlit UI
    already contains all Art. 13 mandatory elements inline.

    Returns:
        Markdown link string, or ``None`` if no static privacy.html exists.
    """
    if _STATIC_PRIVACY_HTML.exists():
        return "[Privacy policy completa](/static/privacy.html)"
    return None


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


def render_privacy_notice(*, lang: str = "it") -> None:
    """Render the GDPR Art. 13 privacy information notice.

    Should be called immediately after (or just before) the login / registration
    form so that the data subject receives the mandatory disclosures before
    submitting their credentials.

    The notice is rendered inside an ``st.expander`` so it does not dominate
    the page while remaining readily accessible.  The expander is collapsed by
    default to avoid visual clutter, but a visible summary line above it signals
    the presence of the notice.

    Args:
        lang: UI language code (``'it'`` or ``'en'``).  Italian is the primary
            audience language per docs/methodology.md; English notice text is
            provided for completeness but Italian takes precedence.
    """
    privacy_link = _privacy_policy_link()
    privacy_link_md = f"\n\n{privacy_link}" if privacy_link else ""

    # A one-line teaser visible without expanding, in both languages so that
    # non-Italian speakers recognise this as a legal disclosure.
    st.caption(
        "ℹ️ I tuoi dati sono trattati in conformità al GDPR (Art. 13). "
        "Espandi per leggere l'informativa completa."
    )

    with st.expander("Informativa sul trattamento dei dati (Art. 13 GDPR)", expanded=False):
        st.markdown(
            f"""
### Informativa sul trattamento dei dati (Art. 13 GDPR)

**Titolare del Trattamento**: {_CONTROLLER_NAME}

I tuoi dati di accesso (username, indirizzo IP, timestamp di login) sono trattati
dal Titolare per la finalità di erogazione del servizio GHG accounting e monitoraggio
della sicurezza degli accessi.

**Base giuridica**: esecuzione del contratto — art. 6(1)(b) GDPR; obbligo di legge
e interesse legittimo per la sicurezza del sistema — art. 6(1)(c) e 6(1)(f) GDPR.

**Periodo di conservazione**: per la durata del rapporto contrattuale e successivamente
archiviati per 10 anni ai sensi della CSRD art. 23(2) e del GDPR art. 6(1)(c) + art. 32
(obbligo di monitoraggio sicurezza).

**Diritti dell'interessato**: in qualità di interessato hai diritto di accesso (art. 15),
rettifica (art. 16), cancellazione (art. 17), limitazione del trattamento (art. 18),
portabilità (art. 20) e opposizione (art. 21) GDPR.
Per esercitare i tuoi diritti contatta il **Responsabile della Protezione dei Dati (DPO)**:
[{_DPO_EMAIL}](mailto:{_DPO_EMAIL})

**Trasferimenti**: i dati non sono trasferiti verso Paesi terzi extra-SEE senza le
garanzie richieste dagli artt. 44-49 GDPR.{privacy_link_md}
"""
        )

    if lang == "en":
        with st.expander("Data processing notice (Art. 13 GDPR) — English summary", expanded=False):
            st.markdown(
                f"""
**Controller**: {_CONTROLLER_NAME}

Your access credentials (username, IP address, login timestamp) are processed by the
Controller for the purpose of delivering the GHG accounting service and monitoring
system security.

**Legal basis**: performance of a contract — Art. 6(1)(b) GDPR; legal obligation and
legitimate interest for system security — Art. 6(1)(c) and 6(1)(f) GDPR.

**Retention**: for the duration of the contractual relationship and subsequently archived
for 10 years (CSRD Art. 23(2); GDPR Art. 6(1)(c) + Art. 32).

**Your rights**: access, rectification, erasure, restriction, portability, objection
(Arts. 15-22 GDPR). Contact the DPO: [{_DPO_EMAIL}](mailto:{_DPO_EMAIL}){privacy_link_md}
"""
            )

"""Help-tooltip dictionary — ESG glossary for the dashboard's "?" icons.

Streamlit widgets accept a ``help`` parameter that renders an info icon
("❓") with a tooltip on hover. We back those tooltips with a centrally
edited glossary so the wording can be reviewed by the SustainabilityExpert
agent and kept consistent across IT/EN.

Usage:
    from ghg_tool.ui.streamlit_app.lib.help import _help

    st.metric(
        label=_("scope1_total", lang),
        value=f"{x:,.1f}",
        help=_help("scope1", lang),
    )

The glossary lives in ``translations/glossary_{lang}.json``. Definitions
have been normatively reviewed against GHG Protocol, ESRS E1, IPCC AR6
and ADR-007.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

_GLOSSARY_DIR: Final[Path] = Path(__file__).parent.parent / "translations"
_SUPPORTED_LANGS: Final[frozenset[str]] = frozenset({"it", "en"})
_DEFAULT_LANG: Final[str] = "it"

_CACHE: dict[str, dict[str, str]] = {}


def _load(lang: str) -> dict[str, str]:
    """Load and cache a glossary file. Falls back to IT if the file is missing."""
    if lang not in _CACHE:
        path = _GLOSSARY_DIR / f"glossary_{lang}.json"
        if not path.exists():
            path = _GLOSSARY_DIR / "glossary_it.json"
        with path.open(encoding="utf-8") as fh:
            _CACHE[lang] = json.load(fh)
    return _CACHE[lang]


def _help(key: str, lang: str = _DEFAULT_LANG) -> str | None:
    """Return the help-tooltip string for ``key`` in ``lang``.

    Returns ``None`` when the key is unknown so Streamlit hides the ❓ icon
    instead of showing a confusing placeholder. The caller can pass the
    result straight to any Streamlit widget's ``help=`` kwarg.

    Args:
        key: Glossary key (snake_case, e.g. ``"scope2_lb"``).
        lang: ISO 639-1 language code; falls back to IT for unsupported codes.

    Returns:
        The tooltip text, or ``None`` if the key is not in the glossary.
    """
    resolved_lang = lang if lang in _SUPPORTED_LANGS else _DEFAULT_LANG
    return _load(resolved_lang).get(key)

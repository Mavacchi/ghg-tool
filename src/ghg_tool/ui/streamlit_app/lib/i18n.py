"""Internationalisation helper — IT/EN translation dictionary loader (FR-33).

Provides a ``_(key, lang)`` function backed by flat JSON dictionaries.
Domain-standard Italian terms (Codice_Sito, Sm³, Gasolio, tCO2e, etc.)
are kept in Italian in both modes per FR-33.

Translations are loaded once at module import and cached in a module-level
dict so that Streamlit reruns never re-read the files from disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

_TRANSLATIONS_DIR: Final[Path] = Path(__file__).parent.parent / "translations"

_SUPPORTED_LANGS: Final[frozenset[str]] = frozenset({"it", "en"})
_DEFAULT_LANG: Final[str] = "it"

# Module-level cache: lang -> key -> value
_CACHE: dict[str, dict[str, str]] = {}


def _load(lang: str) -> dict[str, str]:
    """Load and cache a translation file.

    Args:
        lang: ISO 639-1 language code (``'it'`` or ``'en'``).

    Returns:
        Flat dict mapping translation keys to localised strings.
    """
    if lang not in _CACHE:
        path = _TRANSLATIONS_DIR / f"{lang}.json"
        if not path.exists():
            # Fall back to Italian if file not found (should never happen in prod)
            path = _TRANSLATIONS_DIR / "it.json"
        with path.open(encoding="utf-8") as fh:
            _CACHE[lang] = json.load(fh)
    return _CACHE[lang]


def _(key: str, lang: str = _DEFAULT_LANG) -> str:
    """Translate a key to the requested language.

    Returns the key itself if the translation is missing so the UI
    degrades gracefully rather than raising an exception.

    Args:
        key: Translation key (snake_case string).
        lang: Language code; defaults to ``'it'``.  Falls back to ``'it'``
              if an unsupported code is requested.

    Returns:
        Translated string, or the key if not found.
    """
    resolved_lang = lang if lang in _SUPPORTED_LANGS else _DEFAULT_LANG
    translations = _load(resolved_lang)
    return translations.get(key, key)


def supported_languages() -> list[str]:
    """Return the list of supported ISO language codes.

    Returns:
        List of supported language codes.
    """
    return sorted(_SUPPORTED_LANGS)

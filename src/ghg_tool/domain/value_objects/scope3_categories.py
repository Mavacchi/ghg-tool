"""Value object: Scope 3 category labels (Italian, human-readable).

Single source of truth for the mapping ``sub_scope -> category_label``
used in PDF disclosure, dashboard tables and Pareto hot-spot ranking.

No framework imports.  Pure Python so it can be safely imported by the
domain layer, the application services layer and the UI layer alike.
"""

from __future__ import annotations

S3_CATEGORY_LABELS: dict[str, str] = {
    "Cat1": "1 - Beni e servizi acquistati",
    "Cat2": "2 - Beni capitali",
    "Cat3": "3 - Combustibili/energia WTT+T&D",
    "Cat4": "4 - Trasporto upstream",
    "Cat5": "5 - Rifiuti in operazioni",
    "Cat6": "6 - Viaggi di lavoro",
    "Cat7": "7 - Pendolarismo dipendenti",
    "Cat9": "9 - Trasporto downstream",
    "Cat11": "11 - Uso dei prodotti venduti (Omesso - Immateriale)",
    "Cat12": "12 - Fine vita prodotti venduti",
}


def label_for(sub_scope: str) -> str:
    """Return the human-readable IT label for a Scope 3 sub_scope.

    Falls back to the raw sub_scope code when no mapping is registered
    so callers always receive a non-empty string.

    Args:
        sub_scope: The sub_scope code (e.g. ``"Cat1"``).

    Returns:
        Human-readable IT label, or the input string when unknown.
    """
    return S3_CATEGORY_LABELS.get(sub_scope, sub_scope)


__all__ = ["S3_CATEGORY_LABELS", "label_for"]

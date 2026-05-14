"""Domain policy: GWP set enforcement — MG-10, FR-19.

Mixed GWP sets within a single report run are a hard block.
"""

from __future__ import annotations


class MixedGWPSetError(Exception):
    """Raised when more than one GWP set is detected in a single report run."""


def assert_single_gwp_set(gwp_sets: list[str]) -> str:
    """Assert all rows in a run use the same GWP set.

    Args:
        gwp_sets: List of gwp_set values observed in the current run.

    Returns:
        The single GWP set code if validation passes.

    Raises:
        MixedGWPSetError: If more than one distinct gwp_set value is present.
        ValueError: If ``gwp_sets`` is empty.
    """
    if not gwp_sets:
        raise ValueError("gwp_sets list is empty; cannot validate.")
    unique = set(gwp_sets)
    if len(unique) > 1:
        raise MixedGWPSetError(
            f"Mixed GWP sets detected in a single run: {sorted(unique)}. "
            "FR-19 mandates a single GWP set per report run. "
            "AR6 is the CSRD default; AR5 is the EU ETS dual-track (MG-12)."
        )
    return unique.pop()

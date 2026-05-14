"""Historical YoY-delta statistics shared between hot-spot and reconciliation.

When >= 3 historical YoY deltas (== >= 4 years of history) are available
for a given grouping key, this module computes a per-key historical sigma
of the YoY-delta percentage and exposes ``mean + k * sigma`` as the
outlier threshold.  Otherwise the caller is expected to fall back to the
static +/- 20% threshold documented in ``hotspot_service`` and
``reconciliation_service``.

Decimal end-to-end: floats are only used inside ``statistics.pstdev`` and
the result is cast back to ``Decimal`` via ``str()`` before crossing any
public boundary.  No float-binary contamination of stored or returned
values.

Pure-function module: no I/O, no DB, no FastAPI, no Streamlit.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class YoYStatsBaseline:
    """Historical YoY-delta statistics for one grouping key.

    Attributes:
        key: tuple identifying the grouping (e.g. (scope, sub_scope, site)).
        sample_size: number of historical YoY deltas observed.
        mean_pct: mean of historical YoY delta percentages.
        sigma_pct: standard deviation of historical YoY delta percentages.
        is_reliable: True only when sample_size >= 3.
    """

    key: tuple
    sample_size: int
    mean_pct: Decimal
    sigma_pct: Decimal
    is_reliable: bool


def compute_yoy_baseline(
    historical_by_year: Mapping[int, Mapping[tuple, Decimal]],
    *,
    min_sample: int = 3,
) -> dict[tuple, YoYStatsBaseline]:
    """Compute per-key historical YoY-delta sigma from multi-year history.

    Args:
        historical_by_year: outer mapping keyed by year, inner mapping keyed by
            (scope, sub_scope, site_or_None) -> tco2e.
        min_sample: minimum number of YoY deltas required for is_reliable.

    Returns:
        Mapping key -> YoYStatsBaseline.  Keys present in any year are
        included; sigma is computed across all observed YoY transitions
        (year N+1 - year N) / year N.
    """
    if not historical_by_year:
        return {}

    years_sorted = sorted(int(y) for y in historical_by_year.keys())

    # Build deltas per key by walking consecutive years.
    deltas_by_key: dict[tuple, list[Decimal]] = {}
    all_keys: set[tuple] = set()
    for y in years_sorted:
        for k in historical_by_year[y].keys():
            all_keys.add(tuple(k))

    for i in range(len(years_sorted) - 1):
        y_prev = years_sorted[i]
        y_next = years_sorted[i + 1]
        prev_map = historical_by_year[y_prev]
        next_map = historical_by_year[y_next]
        for k in all_keys:
            prev_v = prev_map.get(k)
            next_v = next_map.get(k)
            if prev_v is None or next_v is None:
                continue
            prev_d = prev_v if isinstance(prev_v, Decimal) else Decimal(str(prev_v))
            next_d = next_v if isinstance(next_v, Decimal) else Decimal(str(next_v))
            if prev_d == _ZERO:
                continue
            pct = (next_d - prev_d) / prev_d * _HUNDRED
            deltas_by_key.setdefault(k, []).append(pct)

    out: dict[tuple, YoYStatsBaseline] = {}
    for k in sorted(all_keys):
        deltas = deltas_by_key.get(k, [])
        n = len(deltas)
        if n == 0:
            mean_pct = _ZERO
            sigma_pct = _ZERO
        elif n == 1:
            mean_pct = deltas[0]
            sigma_pct = _ZERO
        else:
            # Cast through float for statistics, then back to Decimal via str()
            # so the public surface stays Decimal-clean.
            mean_f = statistics.fmean(float(d) for d in deltas)
            sigma_f = statistics.pstdev((float(d) for d in deltas), mu=mean_f)
            mean_pct = Decimal(str(mean_f))
            sigma_pct = Decimal(str(sigma_f))
        out[k] = YoYStatsBaseline(
            key=k,
            sample_size=n,
            mean_pct=mean_pct,
            sigma_pct=sigma_pct,
            is_reliable=n >= min_sample,
        )
    return out


def threshold_pct(
    baseline: YoYStatsBaseline | None,
    *,
    sigma_multiplier: Decimal = Decimal("2"),
    fallback_pct: Decimal = Decimal("20"),
) -> Decimal:
    """Return the outlier threshold percent for one key.

    If baseline is None or not reliable, returns ``fallback_pct``.
    Otherwise returns ``|mean_pct| + sigma_multiplier * sigma_pct``.

    The absolute value on ``mean_pct`` keeps the threshold a positive
    half-width: the caller compares ``abs(yoy_delta_pct) > threshold``.
    """
    if baseline is None or not baseline.is_reliable:
        return fallback_pct
    return abs(baseline.mean_pct) + sigma_multiplier * baseline.sigma_pct


__all__ = ["YoYStatsBaseline", "compute_yoy_baseline", "threshold_pct"]

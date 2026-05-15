"""Historical YoY-delta statistics shared between hot-spot and reconciliation.

When >= 3 historical YoY deltas (== >= 4 years of history) are available
for a given grouping key, this module computes a per-key historical sigma
of the YoY-delta percentage and exposes ``|mean| + k * sigma`` as the
outlier threshold. Otherwise the caller is expected to fall back to the
static +/- 20% threshold documented in ``hotspot_service`` and
``reconciliation_service``.

Sample stdev (M-17):
    ``statistics.stdev`` (Bessel-corrected, divisor N-1) is used rather
    than ``statistics.pstdev`` (population stdev, divisor N). The deltas
    are treated as a finite SAMPLE from an unknown distribution; the
    sample stdev is the standard inferential choice and the conservative
    one against an external auditor. Using pstdev would have UNDER-stated
    sigma by sqrt(N/(N-1)) and produced too many false-positive outlier
    flags. When N < 2 sigma is set to Decimal('0'); the reliability gate
    (sample_size >= min_sample, default 3) prevents the zero-sigma path
    from contaminating downstream thresholds.

Decimal end-to-end: floats are only used inside ``statistics.fmean`` and
``statistics.stdev`` and the result is cast back to ``Decimal`` via
``str()`` before crossing any public boundary. No float-binary
contamination of stored or returned values.

Pure-function module: no I/O, no DB, no FastAPI, no Streamlit.

Methodology references:
  * IAASB ISA 320 Section A3-A14 (materiality thresholds; statistical
    sample treatment under audit standards)
  * GHG Protocol Corporate Standard Chapter 5 (significance thresholds)
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import TypeAlias

#: Generic grouping key shared by hotspot ((sub_scope,)) and reconciliation
#: ((scope, sub_scope, codice_sito)). R-19 / R-20: replaces the bare ``tuple``
#: annotation which disabled mypy element-type checks. The union covers all
#: known callers; tightening to a typed Literal would require pulling the
#: scope3_categories closed-set into the yoy_stats module.
GroupKey: TypeAlias = tuple[int | str | None, ...]

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class YoYStatsBaseline:
    """Historical YoY-delta statistics for one grouping key.

    Attributes:
        key: tuple identifying the grouping (e.g. (scope, sub_scope, site)
            for reconciliation, (sub_scope,) for hotspot). See ``GroupKey``.
        sample_size: number of historical YoY deltas observed.
        mean_pct: mean of historical YoY delta percentages.
        sigma_pct: sample standard deviation of YoY delta percentages
            (Bessel-corrected, divisor N-1; see module docstring on M-17).
        is_reliable: True only when sample_size >= 3 (i.e. >= 4 years of
            history). The reliability gate is unchanged by the pstdev->stdev
            switch.
    """

    key: GroupKey
    sample_size: int
    mean_pct: Decimal
    sigma_pct: Decimal
    is_reliable: bool


def compute_yoy_baseline(
    historical_by_year: Mapping[int, Mapping[GroupKey, Decimal]],
    *,
    min_sample: int = 3,
) -> dict[GroupKey, YoYStatsBaseline]:
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

    years_sorted = sorted(int(y) for y in historical_by_year)

    # Build deltas per key by walking consecutive years.
    deltas_by_key: dict[GroupKey, list[Decimal]] = {}
    all_keys: set[GroupKey] = set()
    for y in years_sorted:
        for k in historical_by_year[y]:
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

    out: dict[GroupKey, YoYStatsBaseline] = {}
    for k in sorted(all_keys):
        deltas = deltas_by_key.get(k, [])
        n = len(deltas)
        if n == 0:
            mean_pct = _ZERO
            sigma_pct = _ZERO
        elif n < 2:
            # M-17: sample stdev is undefined for N=1; explicit zero rather
            # than relying on statistics.stdev to raise. The is_reliable
            # gate (n >= min_sample, default 3) blocks consumers from using
            # this row as a usable baseline anyway.
            mean_pct = deltas[0]
            sigma_pct = _ZERO
        else:
            # Cast through float for statistics, then back to Decimal via str()
            # so the public surface stays Decimal-clean. M-17: use the
            # Bessel-corrected sample stdev (divisor N-1) rather than the
            # population stdev (divisor N).
            float_deltas = [float(d) for d in deltas]
            mean_f = statistics.fmean(float_deltas)
            sigma_f = statistics.stdev(float_deltas)
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


__all__ = ["GroupKey", "YoYStatsBaseline", "compute_yoy_baseline", "threshold_pct"]

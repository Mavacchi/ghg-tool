"""Domain entity: DQFinding — frozen dataclass for DQ gate results.

No framework imports.  100% unit-testable (NFR-15).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DQFinding:
    """Immutable data quality finding produced by a DQ gate check.

    Attributes:
        rule_id: Rule identifier (e.g. 'DQ-CRIT-01', 'FR-37-DEFAULT').
        severity: 'CRIT', 'WARN', or 'INFO'.
        scope: GHG scope (1, 2, or 3); None for cross-scope findings.
        codice_sito: Site code; None for corporate-level findings.
        anno: Reporting year; None if not applicable.
        metric: Short metric label (e.g. 'facility_coverage_s1').
        trigger_desc: Human-readable description of the trigger.
        blocks_pipeline: True if this finding must stop the ETL run.
        value_observed: Observed metric value; None if not numeric.
        value_reference: Reference / threshold value; None if not applicable.
        z_score: Z-score for outlier findings; None otherwise.
        ratio_yoy: Year-over-year ratio; None if not applicable.
        dq_report_version: Version tag for the finding batch.
        extra: Any additional structured context.
    """

    rule_id: str
    severity: str
    scope: int | None = None
    codice_sito: str | None = None
    anno: int | None = None
    metric: str | None = None
    trigger_desc: str = ""
    blocks_pipeline: bool = False
    value_observed: float | None = None
    value_reference: float | None = None
    z_score: float | None = None
    ratio_yoy: float | None = None
    dq_report_version: str = "1.0.0"
    extra: dict[str, Any] | None = None

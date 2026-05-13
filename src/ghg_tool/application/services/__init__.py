"""Application services — wave 2 wiring layer.

These modules orchestrate calls into ``application.calc`` and expose
high-level entry points consumed by the API layer (wave 3) or the CLI.
"""

from ghg_tool.application.services.calc_orchestrator import (
    CalcOrchestrator,
    CalcRunInputs,
)
from ghg_tool.application.services.intensity_service import (
    IntensityReferenceInputs,
    compute_intensities,
)
from ghg_tool.application.services.recalculation_policy import (
    RecalculationDecision,
    evaluate,
)

__all__ = [
    "CalcOrchestrator",
    "CalcRunInputs",
    "IntensityReferenceInputs",
    "RecalculationDecision",
    "compute_intensities",
    "evaluate",
]

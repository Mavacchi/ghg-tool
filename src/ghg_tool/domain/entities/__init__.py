"""Domain entities package — immutable, framework-free dataclasses."""

from ghg_tool.domain.entities.dq_finding import DQFinding
from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.entities.intensity_metric import IntensityMetric

__all__ = ["DQFinding", "EmissionRecord", "IntensityMetric"]

"""Domain ports package — Protocol / ABC interfaces for application layer.

Per the hexagonal architecture (architecture.md §3), application services
depend on these abstract ports rather than concrete infrastructure
adapters.  Infrastructure modules implement these protocols.
"""

from ghg_tool.domain.ports.factor_catalog import FactorCatalogPort, FactorRecord
from ghg_tool.domain.ports.gwp_table import GWPSetTable, GWPTablePort

__all__ = [
    "FactorCatalogPort",
    "FactorRecord",
    "GWPSetTable",
    "GWPTablePort",
]

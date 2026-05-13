"""Domain port: GWPTablePort — GWP100 value table protocol.

Provides a uniform interface for the calc modules to look up GWP100
values per substance, decoupling them from the concrete representation
in ``ghg_tool.domain.value_objects.gwp_set``.

The default implementation (``GWPSetTable``) wraps the
``GWPValues`` dataclass; alternative implementations (e.g. testing
doubles) can be supplied at orchestration time.

No framework imports — pure Python stdlib + typing only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from ghg_tool.domain.value_objects.gwp_set import GWPValues


class GWPTablePort(Protocol):
    """Abstract port for GWP100 value look-up by substance.

    All calc modules accept a ``GWPTablePort`` instance and call
    ``get(substance_code)`` to retrieve the GWP100 multiplier.
    A single instance is used per ``correlation_id`` to satisfy MG-10
    (no mixed-GWP sets within a run).

    The ``code`` attribute reports which IPCC report this table represents,
    so calc modules can stamp the ``gwp_set`` field on emitted records.
    """

    @property
    def code(self) -> str:
        """The IPCC assessment-report code ('AR6' or 'AR5')."""
        ...  # pragma: no cover

    def get(self, substance: str) -> Decimal:
        """Return the GWP100 value for a substance.

        Args:
            substance: One of {'CO2', 'CH4', 'N2O', 'SF6', 'HFC-134a'}.

        Returns:
            ``Decimal`` GWP100 multiplier.

        Raises:
            KeyError: If the substance is not in the table.
        """
        ...  # pragma: no cover


class GWPSetTable:
    """Concrete adapter wrapping ``GWPValues`` to satisfy ``GWPTablePort``.

    Attributes:
        values: Underlying canonical ``GWPValues`` instance (AR6 or AR5).
    """

    __slots__ = ("values",)

    def __init__(self, values: GWPValues) -> None:
        """Initialise with a ``GWPValues`` canonical instance.

        Args:
            values: One of ``ghg_tool.domain.value_objects.gwp_set.AR6``
                or ``AR5``.
        """
        self.values = values

    @property
    def code(self) -> str:
        """The IPCC assessment-report code ('AR6' or 'AR5')."""
        return self.values.code

    def get(self, substance: str) -> Decimal:
        """Return the GWP100 value for a substance.

        Args:
            substance: Substance code; case-insensitive normalised to upper.

        Returns:
            ``Decimal`` GWP100 multiplier.

        Raises:
            KeyError: If the substance is not in the table.
        """
        key = substance.upper().replace("_", "-")
        # Map substance codes to GWPValues attributes
        mapping: dict[str, Decimal] = {
            "CO2": self.values.co2,
            "CH4": self.values.ch4,
            "N2O": self.values.n2o,
            "SF6": self.values.sf6,
            "HFC-134A": self.values.hfc134a,
        }
        if key not in mapping:
            raise KeyError(
                f"Unknown substance code: {substance!r}. "
                f"Allowed: {sorted(mapping.keys())}"
            )
        return mapping[key]

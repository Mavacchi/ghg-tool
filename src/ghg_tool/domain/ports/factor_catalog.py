"""Domain port: FactorCatalogPort — abstract factor catalog access.

Per architecture.md §3 hexagonal layering: ``application/calc`` modules
depend on this Protocol, not on any concrete repository implementation.
The infrastructure layer wires
``infrastructure.db.repositories.factor_catalog_repository.FactorCatalogRepository``
to satisfy the protocol at runtime.

No framework imports — pure Python stdlib + typing only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class FactorRecord:
    """Domain-side projection of a row in ``ref.factor_catalog``.

    The calc modules consume this lightweight record rather than the ORM
    model so the domain stays SQLAlchemy-free.  The infrastructure adapter
    (``factor_catalog_repository``) converts ORM rows into ``FactorRecord``
    instances on read.

    Attributes:
        factor_id: String identifier (e.g. 'STOICH_CACO3_IPCC_2006').
        version: Version tag of the factor (e.g. '2025').
        value: Numeric factor value as ``Decimal``.  ``None`` if licence-only
            and not yet pinned at runtime.
        unit: Unit of the factor (e.g. 'kg CO2e / kWh').
        source: Provider string ('DEFRA', 'ISPRA', 'AIB', 'ecoinvent v3.10',
            'IPCC', 'EXIOBASE').
        gwp_set: GWP set tag ('AR6' or 'AR5').
        biogenic_co2_kg_per_unit: ADR-007 companion column — biogenic CO2 in
            kg per functional unit; populated for cardboard / pallet factors
            and ``None`` otherwise.
        vintage: Vintage year tag ('2024', '2025', 'n/a').
        applicability_note: Free-text applicability annotation.
        is_tbc: Flag — factor value still pending Phase 5 numeric pinning.
        is_licence_only: Flag — provider licence forbids republishing the
            numeric value (ecoinvent / EXIOBASE).
        factor_db_id: Primary-key UUID of the ``ref.factor_catalog`` row.
            ``None`` when constructed by test doubles that do not need the DB
            UUID.  When non-None it is used as the FK value in
            ``calc.emissions_consolidated.factor_id`` to satisfy the FK
            constraint without falling back to the nil UUID sentinel.
    """

    factor_id: str
    version: str
    value: Decimal | None
    unit: str
    source: str
    gwp_set: str
    biogenic_co2_kg_per_unit: Decimal | None = None
    vintage: str | None = None
    applicability_note: str | None = None
    is_tbc: bool = False
    is_licence_only: bool = False
    factor_db_id: uuid.UUID | None = field(default=None, compare=False)


class FactorCatalogPort(Protocol):
    """Abstract port for read-only access to the factor catalog.

    Implementations live in the infrastructure layer.  Concrete
    ``FactorCatalogRepository`` (SQLAlchemy) and in-memory test doubles
    must both satisfy this protocol.

    All look-ups are scoped to a single GWP set: AR6 (CSRD default) or
    AR5 (EU ETS dual-track per FR-34).  A factor missing from the catalog
    raises ``MissingFactorError`` at the use-site of the calc module.
    """

    def get(
        self,
        factor_id: str,
        *,
        gwp_set: str,
        vintage_year: int | None = None,
    ) -> FactorRecord:
        """Return the active ``FactorRecord`` for the given factor_id and gwp_set.

        Args:
            factor_id: Catalog key (e.g. 'WTT_GAS_NAT_DEFRA_2025').
            gwp_set: 'AR6' or 'AR5'.
            vintage_year: Optional vintage filter; falls back to the
                ``valid_to IS NULL`` active row when ``None``.

        Returns:
            The matching ``FactorRecord``.

        Raises:
            MissingFactorError: When no active row is found.
        """
        ...  # pragma: no cover

    def get_biogenic_share(self, factor_id: str, *, gwp_set: str) -> Decimal | None:
        """Return the biogenic CO2 share for an ADR-007 factor.

        Used by ``scope3_cat1_purchased_goods`` to populate the
        ``co2_biogenic_tonne`` companion column on cardboard / pallet
        EmissionRecords.  Returns ``None`` for non-biogenic factors.

        Args:
            factor_id: Catalog key.
            gwp_set: 'AR6' or 'AR5'.

        Returns:
            Biogenic CO2 share (kg CO2 / kg material) as ``Decimal``,
            or ``None`` if the factor carries no biogenic split.
        """
        ...  # pragma: no cover

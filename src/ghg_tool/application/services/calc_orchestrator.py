"""Calculation orchestration — wires the 16 calc modules per architecture.md §8.4.

Pure-function orchestrator: no DB I/O.  Returns the combined
``list[EmissionRecord]`` from all 16 modules for a given run context.
Persistence is the caller's responsibility (typically the backend service
layer in wave 3) — it calls ``EmissionsRepository.insert`` on each record.

Calling convention:
    ``CalcOrchestrator(catalog, gwp_table).run(...)`` accepts the staged
    raw rows already loaded from the DB by the caller, and returns the
    full ``list[EmissionRecord]``.

This keeps the calc package framework-free.  The single-GWP-set
invariant (MG-10) is enforced at construction time (one orchestrator
instance = one GWP table = one ``regulatory_stream``).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ghg_tool.application.calc import (
    scope1_combustion,
    scope1_fugitive_zero,
    scope1_process,
    scope2_lb,
    scope2_mb,
    scope3_cat1_purchased_goods,
    scope3_cat2_capital_goods,
    scope3_cat3_fuel_energy,
    scope3_cat4_upstream_transport,
    scope3_cat5_waste,
    scope3_cat6_business_travel,
    scope3_cat7_commuting,
    scope3_cat9_downstream_transport,
    scope3_cat11_zero_line,
    scope3_cat12_eol,
    scope3_cat_omitted_zero_lines,
)
from ghg_tool.application.calc._helpers import to_decimal
from ghg_tool.application.calc.scope2_mb import GOEvidenceCheck
from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.policies.gwp_enforcement import assert_single_gwp_set
from ghg_tool.domain.ports.factor_catalog import FactorCatalogPort
from ghg_tool.domain.ports.gwp_table import GWPTablePort


@dataclass(frozen=True, slots=True)
class CalcRunInputs:
    """Inputs for a single calc run.

    Attributes:
        correlation_id: Shared run identifier (typically same as ETL batch_id).
        anno: Reporting year (2024 or 2025).
        sites: Iterable of site codes for fugitive zero-line emission.
        scope1_rows: Iterable of raw Scope 1 row dicts.
        scope2_rows: Iterable of raw Scope 2 row dicts.
        scope3_rows: Iterable of raw Scope 3 row dicts.
        created_by: User / service-account identifier.
        regulatory_stream: 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.
        go_evidence: Optional GO evidence check stub override.
    """

    correlation_id: uuid.UUID
    anno: int
    sites: tuple[str, ...]
    scope1_rows: tuple[Mapping[str, Any], ...]
    scope2_rows: tuple[Mapping[str, Any], ...]
    scope3_rows: tuple[Mapping[str, Any], ...]
    created_by: str = "calc_orchestrator"
    regulatory_stream: str = "CSRD_ESRS_E1"
    go_evidence: GOEvidenceCheck | None = field(default=None)


class CalcOrchestrator:
    """Wires the 16 calc modules into a deterministic sequence.

    One instance binds a single ``FactorCatalogPort`` and ``GWPTablePort``;
    one ``run()`` invocation produces one consolidated emission row stream.

    For FR-34 EU ETS dual-track, the caller constructs **two**
    ``CalcOrchestrator`` instances — one with AR6 + 'CSRD_ESRS_E1', one
    with AR5 + 'EU_ETS_PHASE_IV' — and runs each in turn.  See
    architecture.md §11 for the dual-write contract.
    """

    __slots__ = ("_catalog", "_gwp")

    def __init__(
        self,
        catalog: FactorCatalogPort,
        gwp: GWPTablePort,
    ) -> None:
        """Initialise with catalog + GWP table.

        Args:
            catalog: Factor catalog port.
            gwp: GWP100 look-up table (AR6 or AR5).
        """
        self._catalog = catalog
        self._gwp = gwp

    def run(self, inputs: CalcRunInputs) -> list[EmissionRecord]:
        """Execute the 16 calc modules in dependency order.

        Sequence (matches architecture.md §8.4):
            1. fugitive_zero (FR-35)
            2. scope1_combustion (FR-05)
            3. scope1_process (FR-06)
            4. compute Σ Scope 1 by (combustibile, anno) [in-memory]
            5. scope2_lb (FR-07)
            6. scope2_mb (FR-08)
            7. compute Σ Scope 2 kWh by anno [in-memory]
            8. scope3_cat1 .. scope3_cat12 + zero-lines
            9. enforce single-GWP-set invariant on emitted rows

        Args:
            inputs: Bundled run inputs.

        Returns:
            Full ``list[EmissionRecord]`` in deterministic insertion order.
        """
        rows: list[EmissionRecord] = []
        ctx = self._common_ctx(inputs)

        rows.extend(scope1_fugitive_zero.calculate(
            inputs.sites, self._catalog, self._gwp,
            anno=inputs.anno, **ctx,
        ))
        rows.extend(scope1_combustion.calculate(
            inputs.scope1_rows, self._catalog, self._gwp, **ctx,
        ))
        rows.extend(scope1_process.calculate(
            inputs.scope1_rows, self._catalog, self._gwp, **ctx,
        ))

        sigma_s1 = _sigma_scope1_from_rows(inputs.scope1_rows)
        sigma_s2 = _sigma_scope2_from_rows(inputs.scope2_rows)

        rows.extend(scope2_lb.calculate(
            inputs.scope2_rows, self._catalog, self._gwp, **ctx,
        ))
        rows.extend(scope2_mb.calculate(
            inputs.scope2_rows, self._catalog, self._gwp,
            go_evidence=inputs.go_evidence,
            **ctx,
        ))

        rows.extend(scope3_cat1_purchased_goods.calculate(
            inputs.scope3_rows, self._catalog, self._gwp, **ctx,
        ))
        rows.extend(scope3_cat2_capital_goods.calculate(
            inputs.scope3_rows, self._catalog, self._gwp, **ctx,
        ))
        rows.extend(scope3_cat3_fuel_energy.calculate(
            sigma_scope1=sigma_s1,
            sigma_scope2_kwh=sigma_s2,
            factors=self._catalog,
            gwp=self._gwp,
            **ctx,
        ))
        rows.extend(scope3_cat4_upstream_transport.calculate(
            inputs.scope3_rows, self._catalog, self._gwp, **ctx,
        ))
        rows.extend(scope3_cat5_waste.calculate(
            inputs.scope3_rows, self._catalog, self._gwp, **ctx,
        ))
        rows.extend(scope3_cat6_business_travel.calculate(
            inputs.scope3_rows, self._catalog, self._gwp, **ctx,
        ))
        rows.extend(scope3_cat7_commuting.calculate(
            inputs.scope3_rows, self._catalog, self._gwp, **ctx,
        ))
        rows.extend(scope3_cat9_downstream_transport.calculate(
            inputs.scope3_rows, self._catalog, self._gwp, **ctx,
        ))
        rows.extend(scope3_cat12_eol.calculate(
            inputs.scope3_rows, self._catalog, self._gwp, **ctx,
        ))
        rows.extend(scope3_cat11_zero_line.calculate(
            self._catalog, self._gwp, anno=inputs.anno, **ctx,
        ))
        rows.extend(scope3_cat_omitted_zero_lines.calculate(
            self._catalog, self._gwp, anno=inputs.anno, **ctx,
        ))

        # MG-10 final check: enforce single GWP set across all emitted rows.
        assert_single_gwp_set([r.gwp_set for r in rows])
        return rows

    @staticmethod
    def _common_ctx(inputs: CalcRunInputs) -> dict[str, Any]:
        """Build the kwargs common to all calc-module ``calculate`` calls.

        Args:
            inputs: Run inputs bundle.

        Returns:
            Dict with correlation_id, created_by, regulatory_stream keys.
        """
        return {
            "correlation_id": inputs.correlation_id,
            "created_by": inputs.created_by,
            "regulatory_stream": inputs.regulatory_stream,
        }


# ---------------------------------------------------------------------------
# Σ helpers (FR-11 source-of-truth aggregations)
# ---------------------------------------------------------------------------

def _sigma_scope1_from_rows(
    rows: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, int], Decimal]:
    """Aggregate raw Scope 1 rows into Σ by (combustibile, anno).

    Process emissions (categoria_s1='Processo_Decarb') are excluded since
    Cat 3 WTT applies to fuel inputs only.

    Args:
        rows: Iterable of raw Scope 1 row dicts.

    Returns:
        Dict ``(combustibile, anno) -> Σ quantita`` as ``Decimal``.
    """
    sigma: dict[tuple[str, int], Decimal] = {}
    for row in rows:
        if str(row.get("categoria_s1", "")) == "Processo_Decarb":
            continue
        combustibile = str(row["combustibile"])
        anno = int(row["anno"])
        qty = to_decimal(row["quantita"])
        key = (combustibile, anno)
        sigma[key] = sigma.get(key, Decimal("0")) + qty
    return sigma


def _sigma_scope2_from_rows(
    rows: Iterable[Mapping[str, Any]],
) -> dict[int, Decimal]:
    """Aggregate raw Scope 2 rows into Σ kWh by year (LB basis).

    Args:
        rows: Iterable of raw Scope 2 row dicts.

    Returns:
        Dict ``anno -> Σ kWh`` as ``Decimal``.
    """
    sigma: dict[int, Decimal] = {}
    for row in rows:
        anno = int(row["anno"])
        qty = to_decimal(row["quantita"])
        sigma[anno] = sigma.get(anno, Decimal("0")) + qty
    return sigma

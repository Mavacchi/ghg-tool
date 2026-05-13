"""Scope 2 — Market-Based emissions (FR-08, MG-03, MG-14).

Per requirements.md FR-08:
  - GO-covered volumes apply factor ``MB_GO_ZERO`` (0 tCO2e/MWh) only when
    the per-certificate QC1–QC8 evidence is validated (MG-03 / MG-14);
  - Otherwise residual mix factor ``MB_IT_RESIDUAL_AIB_2024`` applies.

For wave 2, the GO evidence lookup is decoupled behind the
``GOEvidenceCheck`` protocol — concrete repository wiring lives in the
infrastructure / backend layer.  A default stub returns ``True`` when
the row carries ``strumento_mb='GO_GSE'``; backend wires the real
evidence-table lookup later.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any, Protocol

from ghg_tool.application.calc._helpers import (
    KG_TO_TONNE,
    make_emission,
    require_factor,
    to_decimal,
)
from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.exceptions.calc_errors import GOValidationError
from ghg_tool.domain.ports.factor_catalog import FactorCatalogPort
from ghg_tool.domain.ports.gwp_table import GWPTablePort

_FACTOR_ID_GO_ZERO = "MB_GO_ZERO"
_FACTOR_ID_RESIDUAL = "MB_IT_RESIDUAL_AIB_2024"
_GO_INSTRUMENT_LABEL = "GO_GSE"


class GOEvidenceCheck(Protocol):
    """Port for the per-certificate QC1–QC8 evidence look-up (MG-14)."""

    def is_validated(
        self,
        *,
        codice_sito: str,
        anno: int,
        strumento_mb: str | None,
    ) -> bool:
        """Return ``True`` when the GO covering the row passes all 8 QCs.

        Args:
            codice_sito: Site code of the raw row.
            anno: Reporting year.
            strumento_mb: Market-based instrument label.

        Returns:
            True if QC1..QC8 all pass for the covering GO.
        """
        ...  # pragma: no cover


class _DefaultGOEvidenceCheck:
    """Default stub: validate any row tagged ``strumento_mb='GO_GSE'``.

    Backend will replace this with a repository-backed adapter that reads
    ``ref.v_go_certificate_qc_pass`` (the AND-of-eight view).  For now
    the stub keeps the calc layer testable in isolation.
    """

    def is_validated(
        self,
        *,
        codice_sito: str,  # noqa: ARG002 — interface; backend wires real query
        anno: int,  # noqa: ARG002
        strumento_mb: str | None,
    ) -> bool:
        """Validate via the lightweight stub rule.

        Args:
            codice_sito: Site code (unused in stub).
            anno: Reporting year (unused in stub).
            strumento_mb: 'GO_GSE' → validated, else False.

        Returns:
            True only when ``strumento_mb == 'GO_GSE'``.
        """
        return strumento_mb == _GO_INSTRUMENT_LABEL


def calculate(  # noqa: PLR0913 — explicit named DI for testability
    raw_rows: Iterable[Mapping[str, Any]],
    factors: FactorCatalogPort,
    gwp: GWPTablePort,
    *,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str = "CSRD_ESRS_E1",
    go_evidence: GOEvidenceCheck | None = None,
) -> list[EmissionRecord]:
    """Compute Scope 2 MB EmissionRecords with GO-gated zero / residual fallback.

    Args:
        raw_rows: Iterable of raw Scope 2 row dicts.
        factors: Factor catalog port.
        gwp: GWP100 lookup port.
        correlation_id: Shared run identifier.
        created_by: User / service-account identifier.
        regulatory_stream: 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.
        go_evidence: GO evidence checker; defaults to the stub validator.

    Returns:
        List of ``EmissionRecord`` instances with ``sub_scope='MB'``.

    Raises:
        GOValidationError: If a row tagged 'GO_GSE' fails QC validation
            but the calculation path would have produced an MB=0 row — the
            calc raises to surface the policy violation instead of silently
            applying residual mix to GO-tagged volumes.
    """
    checker = go_evidence if go_evidence is not None else _DefaultGOEvidenceCheck()
    zero_factor = require_factor(factors, _FACTOR_ID_GO_ZERO, gwp_set=gwp.code)
    residual_factor = require_factor(factors, _FACTOR_ID_RESIDUAL, gwp_set=gwp.code)

    records: list[EmissionRecord] = []
    for row in raw_rows:
        records.append(
            _build_mb_record(
                row=row,
                zero_factor=zero_factor,
                residual_factor=residual_factor,
                gwp=gwp,
                checker=checker,
                correlation_id=correlation_id,
                created_by=created_by,
                regulatory_stream=regulatory_stream,
            )
        )
    return records


def _build_mb_record(  # noqa: PLR0913 — internal builder dispatch
    *,
    row: Mapping[str, Any],
    zero_factor: Any,
    residual_factor: Any,
    gwp: GWPTablePort,
    checker: GOEvidenceCheck,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str,
) -> EmissionRecord:
    """Build one MB EmissionRecord with GO-gating decision logic.

    Args:
        row: Raw Scope 2 row dict.
        zero_factor: Looked-up MB_GO_ZERO factor record.
        residual_factor: Looked-up MB_IT_RESIDUAL_AIB_2024 factor record.
        gwp: GWP100 lookup port.
        checker: GO evidence checker.
        correlation_id: Run identifier.
        created_by: User identifier.
        regulatory_stream: Stream tag.

    Returns:
        New ``EmissionRecord``.

    Raises:
        GOValidationError: If the row was tagged as GO but QC failed.
    """
    quantita_kwh = to_decimal(row["quantita"])
    strumento = row.get("strumento_mb")
    codice_sito = str(row["codice_sito"])
    anno = int(row["anno"])

    is_go_tagged = strumento == _GO_INSTRUMENT_LABEL
    if is_go_tagged:
        passed = checker.is_validated(
            codice_sito=codice_sito, anno=anno, strumento_mb=strumento
        )
        if not passed:
            raise GOValidationError(
                f"Row tagged strumento_mb='GO_GSE' for site={codice_sito} "
                f"anno={anno} failed QC1-QC8 validation; MG-14 blocks MB=0 "
                "application.  Investigate evidence row before calc."
            )
        factor = zero_factor
        tco2e = Decimal("0")
        disclosure = (
            f"Scope 2 MB: GO_GSE validated (QC1-QC8 passed); applied factor "
            f"{zero_factor.factor_id} (0 tCO2e/MWh)."
        )
    else:
        factor = residual_factor
        tco2e = (residual_factor.value or Decimal("0")) * quantita_kwh * KG_TO_TONNE
        disclosure = (
            f"Scope 2 MB: residual mix applied to {quantita_kwh} kWh "
            f"(strumento_mb={strumento!s}); factor {residual_factor.factor_id}."
        )

    return make_emission(
        correlation_id=correlation_id,
        raw_row_id=_uuid_or_none(row.get("id")),
        scope=2,
        sub_scope="MB",
        codice_sito=codice_sito,
        anno=anno,
        tco2e=tco2e,
        factor=factor,
        gwp_set=gwp.code,
        methodology="market-based",
        regulatory_stream=regulatory_stream,
        created_by=created_by,
        co2_tonne=tco2e,
        co2_fossil_tonne=tco2e,
        disclosure_notes=disclosure,
    )


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    """Coerce a value to UUID if possible; else None.

    Args:
        value: Source value (UUID, str, or None).

    Returns:
        ``uuid.UUID`` instance or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))

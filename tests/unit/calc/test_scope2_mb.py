"""Unit tests for scope2_mb.calculate (FR-08, MG-03, MG-14)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from ghg_tool.application.calc import scope2_mb
from ghg_tool.domain.exceptions.calc_errors import GOValidationError
from tests.unit.calc.conftest import InMemoryFactorCatalog


class _AlwaysFalseChecker:
    """Stub GOEvidenceCheck that always fails QC validation."""

    def is_validated(
        self, *, codice_sito: str, anno: int, strumento_mb: str | None,  # noqa: ARG002
    ) -> bool:
        return False


class _AlwaysTrueChecker:
    """Stub GOEvidenceCheck that always passes QC validation."""

    def is_validated(
        self, *, codice_sito: str, anno: int, strumento_mb: str | None,  # noqa: ARG002
    ) -> bool:
        return True


def _s2_row(
    *, quantita: str = "1000000", strumento_mb: str | None = "GO_GSE",
    codice_sito: str = "IANO", anno: int = 2024,
    voce_s2: str = "EE_Acquistata_GO",
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "quantita": quantita,
        "codice_sito": codice_sito,
        "anno": anno,
        "voce_s2": voce_s2,
        "strumento_mb": strumento_mb,
    }


def test_mb_go_validated_applies_zero(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope2_mb.calculate(
        [_s2_row(strumento_mb="GO_GSE")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
        go_evidence=_AlwaysTrueChecker(),
    )
    assert out[0].tco2e == Decimal("0")
    assert out[0].factor_id == "MB_GO_ZERO"


def test_mb_grid_residual_applies_when_not_go(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope2_mb.calculate(
        [_s2_row(strumento_mb="Grid_Residual", quantita="1000000")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    # 1,000,000 × 0.44 × 0.001 = 440 tCO2e
    assert out[0].tco2e == Decimal("440.000")
    assert out[0].factor_id == "MB_IT_RESIDUAL_AIB_2024"


def test_mb_default_stub_validates_go_gse(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    """Default stub: rows tagged GO_GSE are auto-validated."""
    out = scope2_mb.calculate(
        [_s2_row(strumento_mb="GO_GSE")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].tco2e == Decimal("0")


def test_mb_default_stub_residual_for_other(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope2_mb.calculate(
        [_s2_row(strumento_mb="Grid_Residual")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].factor_id == "MB_IT_RESIDUAL_AIB_2024"


def test_mb_go_tagged_but_qc_failed_raises(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    with pytest.raises(GOValidationError):
        scope2_mb.calculate(
            [_s2_row(strumento_mb="GO_GSE")], catalog, ar6_gwp,
            correlation_id=correlation_id, created_by="t",
            go_evidence=_AlwaysFalseChecker(),
        )


def test_mb_methodology_market_based(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope2_mb.calculate(
        [_s2_row()], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
        go_evidence=_AlwaysTrueChecker(),
    )
    assert out[0].methodology == "market-based"
    assert out[0].sub_scope == "MB"


def test_mb_string_id_coerced(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _s2_row(strumento_mb="Grid_Residual")
    row["id"] = str(row["id"])
    out = scope2_mb.calculate(
        [row], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert isinstance(out[0].raw_row_id, uuid.UUID)


def test_mb_none_id(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _s2_row(strumento_mb="Grid_Residual")
    row["id"] = None
    out = scope2_mb.calculate(
        [row], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].raw_row_id is None

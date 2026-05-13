"""Property test: tco2e ≥ 0 for every emitted ``EmissionRecord``.

Generates randomised Scope 1 / Scope 2 raw rows and runs the
corresponding calc module; asserts that all outputs have non-negative
tco2e (and the related component columns).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ghg_tool.application.calc import (
    scope1_combustion,
    scope1_process,
    scope2_lb,
    scope2_mb,
    scope3_cat1_purchased_goods,
)


@given(
    combustibile=st.sampled_from(["GAS_NAT", "GASOLIO", "BENZINA"]),
    quantita=st.decimals(min_value=Decimal("0"), max_value=Decimal("1e7"),
                         allow_nan=False, allow_infinity=False, places=2),
)
@settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_scope1_combustion_non_negative(
    combustibile: str, quantita: Decimal,
    catalog, ar6_gwp, correlation_id,
) -> None:
    rows = [{
        "id": uuid.uuid4(),
        "combustibile": combustibile,
        "quantita": str(quantita),
        "codice_sito": "IANO",
        "anno": 2024,
        "categoria_s1": "Combustione stazionaria",
    }]
    out = scope1_combustion.calculate(
        rows, catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert all(r.tco2e >= Decimal("0") for r in out)
    assert all(r.co2_tonne is None or r.co2_tonne >= Decimal("0") for r in out)


@given(quantita=st.decimals(min_value=Decimal("0"), max_value=Decimal("1e6"),
                            allow_nan=False, allow_infinity=False, places=2))
@settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_scope1_process_non_negative(
    quantita: Decimal, catalog, ar6_gwp, correlation_id,
) -> None:
    rows = [{
        "id": uuid.uuid4(),
        "combustibile": "CACO3",
        "quantita": str(quantita),
        "codice_sito": "IANO",
        "anno": 2024,
        "categoria_s1": "Processo_Decarb",
    }]
    out = scope1_process.calculate(
        rows, catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert all(r.tco2e >= Decimal("0") for r in out)


@given(quantita=st.decimals(min_value=Decimal("0"), max_value=Decimal("1e8"),
                            allow_nan=False, allow_infinity=False, places=0))
@settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_scope2_lb_non_negative(
    quantita: Decimal, catalog, ar6_gwp, correlation_id,
) -> None:
    rows = [{
        "id": uuid.uuid4(),
        "quantita": str(quantita),
        "codice_sito": "IANO",
        "anno": 2024,
        "voce_s2": "EE_Acquistata_Grid",
    }]
    out = scope2_lb.calculate(
        rows, catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert all(r.tco2e >= Decimal("0") for r in out)


@given(quantita=st.decimals(min_value=Decimal("0"), max_value=Decimal("1e8"),
                            allow_nan=False, allow_infinity=False, places=0))
@settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_scope2_mb_residual_non_negative(
    quantita: Decimal, catalog, ar6_gwp, correlation_id,
) -> None:
    rows = [{
        "id": uuid.uuid4(),
        "quantita": str(quantita),
        "codice_sito": "IANO",
        "anno": 2024,
        "voce_s2": "EE_Acquistata_Grid",
        "strumento_mb": "Grid_Residual",
    }]
    out = scope2_mb.calculate(
        rows, catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert all(r.tco2e >= Decimal("0") for r in out)


@given(
    quantita=st.decimals(min_value=Decimal("0"), max_value=Decimal("1e5"),
                         allow_nan=False, allow_infinity=False, places=2),
    sottocategoria=st.sampled_from([
        "Argille", "Imballaggi cartone", "Pallet legno",
    ]),
)
@settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_scope3_cat1_non_negative_including_biogenic(
    quantita: Decimal, sottocategoria: str,
    catalog, ar6_gwp, correlation_id,
) -> None:
    rows = [{
        "id": uuid.uuid4(),
        "sottocategoria": sottocategoria,
        "quantita": str(quantita),
        "anno": 2024,
        "categoria_s3": 1,
    }]
    out = scope3_cat1_purchased_goods.calculate(
        rows, catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    for r in out:
        assert r.tco2e >= Decimal("0")
        assert r.co2_biogenic_tonne is None or r.co2_biogenic_tonne >= Decimal("0")
        assert r.co2_fossil_tonne is None or r.co2_fossil_tonne >= Decimal("0")

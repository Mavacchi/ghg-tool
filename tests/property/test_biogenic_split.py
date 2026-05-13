"""Property test: ADR-007 biogenic split coherence.

For cardboard / pallet (Cat 1) factors with a biogenic share:
  * ``co2_biogenic_tonne`` is set
  * ``co2_fossil_tonne`` is set
  * ``co2_biogenic_tonne >= 0`` and ``co2_fossil_tonne >= 0``
  * ``tco2e`` equals the (fossil + non-CO2 GWP-weighted) component;
    biogenic remains memo-only and is NOT netted into ``tco2e``
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ghg_tool.application.calc import scope3_cat1_purchased_goods


@given(
    mass_kg=st.decimals(
        min_value=Decimal("1"), max_value=Decimal("1e5"),
        allow_nan=False, allow_infinity=False, places=2,
    ),
    sottocategoria=st.sampled_from(["Imballaggi cartone", "Pallet legno"]),
)
@settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_biogenic_columns_populated_and_memo_only(
    mass_kg: Decimal, sottocategoria: str,
    catalog, ar6_gwp, correlation_id,
) -> None:
    row = {
        "id": uuid.uuid4(),
        "sottocategoria": sottocategoria,
        "quantita": str(mass_kg),
        "anno": 2024,
        "categoria_s3": 1,
    }
    out = scope3_cat1_purchased_goods.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    rec = out[0]
    # ADR-007: both columns set on biogenic factors
    assert rec.co2_biogenic_tonne is not None
    assert rec.co2_fossil_tonne is not None
    # Non-negative
    assert rec.co2_biogenic_tonne >= Decimal("0")
    assert rec.co2_fossil_tonne >= Decimal("0")
    # tco2e = fossil + non-CO2 component (= co2_fossil_tonne here since
    # the test factor is CO2e total with biogenic share separately)
    assert rec.tco2e == rec.co2_fossil_tonne
    # Biogenic memo NOT netted into tco2e: in particular when biogenic > 0,
    # tco2e remains positive (no subtraction).
    assert rec.tco2e >= Decimal("0")


@given(mass_kg=st.decimals(
    min_value=Decimal("1"), max_value=Decimal("1e5"),
    allow_nan=False, allow_infinity=False, places=2,
))
@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_non_biogenic_factor_has_no_biogenic_columns(
    mass_kg: Decimal, catalog, ar6_gwp, correlation_id,
) -> None:
    """Non-biogenic Cat 1 (e.g. Argille) → biogenic columns remain None."""
    row = {
        "id": uuid.uuid4(),
        "sottocategoria": "Argille",
        "quantita": str(mass_kg),
        "anno": 2024,
        "categoria_s3": 1,
    }
    out = scope3_cat1_purchased_goods.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    rec = out[0]
    assert rec.co2_biogenic_tonne is None
    assert rec.co2_fossil_tonne is None

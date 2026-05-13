"""Property test (REV-024): Cat 6 bootstrap CI bounds are always Decimal at output.

The internal bootstrap loop converts ``Decimal -> float`` for stdlib
``random`` compatibility, then re-wraps the percentile bounds via
``Decimal(str(...))``.  This test pins the invariant that the EmissionRecord
columns ``uncertainty_band_lower`` / ``uncertainty_band_upper`` never leak
binary-fraction ``float`` values back into the persistence boundary.

See ADR-009 (uncertainty methodology) for the full derivation.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ghg_tool.application.calc import scope3_cat6_business_travel


@given(
    spend=st.decimals(
        min_value=Decimal("1"),
        max_value=Decimal("1e6"),
        allow_nan=False, allow_infinity=False,
        places=2,
    ),
    sottocategoria=st.sampled_from(["Voli", "Auto noleggio", "Hotel"]),
)
@settings(
    max_examples=40,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_bootstrap_ci_bounds_are_decimal(
    spend: Decimal,
    sottocategoria: str,
    catalog, ar6_gwp, correlation_id,
) -> None:
    """REV-024 — both uncertainty bounds are ``Decimal`` instances.

    Even when the bootstrap internals pass through float64, the public
    EmissionRecord columns must stay Decimal-typed so the database
    persistence layer receives no float values.
    """
    row = {
        "id": uuid.uuid4(),
        "sottocategoria": sottocategoria,
        "quantita": str(spend),
        "anno": 2024,
        "categoria_s3": 6,
    }
    out = scope3_cat6_business_travel.calculate(
        [row], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    rec = out[0]
    assert rec.uncertainty_band_lower is not None
    assert rec.uncertainty_band_upper is not None
    # Decimal-type invariant (REV-024)
    assert isinstance(rec.uncertainty_band_lower, Decimal)
    assert isinstance(rec.uncertainty_band_upper, Decimal)
    # Ordering invariant — lower <= upper (degenerate zero-spend case
    # handled separately; non-zero spend always produces a band).
    assert rec.uncertainty_band_lower <= rec.uncertainty_band_upper
    # Non-negativity invariant — emissions cannot be negative.
    assert rec.uncertainty_band_lower >= Decimal("0")


@given(
    spend=st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("1e6"),
        allow_nan=False, allow_infinity=False,
        places=2,
    ),
)
@settings(
    max_examples=20,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_zero_spend_emits_decimal_zero_bounds(
    spend: Decimal,
    catalog, ar6_gwp, correlation_id,
) -> None:
    """Even for the degenerate zero-spend path the bounds remain Decimal.

    The fast-path short-circuit in ``_bootstrap_ci`` must keep the type
    contract intact — no ``int`` zeros, no ``float`` zeros.
    """
    row = {
        "id": uuid.uuid4(),
        "sottocategoria": "Voli",
        "quantita": str(spend),
        "anno": 2024,
        "categoria_s3": 6,
    }
    out = scope3_cat6_business_travel.calculate(
        [row], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    rec = out[0]
    assert isinstance(rec.uncertainty_band_lower, Decimal)
    assert isinstance(rec.uncertainty_band_upper, Decimal)

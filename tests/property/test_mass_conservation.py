"""Property test: stoichiometric mass conservation (Scope 1 process).

For any input CaCO3 mass M, the calc must emit CO2 mass = 0.4397 × M
exactly (precision better than 1e-6).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ghg_tool.application.calc import scope1_process


@given(mass_t=st.decimals(
    min_value=Decimal("0"), max_value=Decimal("1e7"),
    allow_nan=False, allow_infinity=False, places=6,
))
@settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_stoichiometric_factor_exact(
    mass_t: Decimal, catalog, ar6_gwp, correlation_id,
) -> None:
    row = {
        "id": uuid.uuid4(),
        "combustibile": "CACO3",
        "quantita": str(mass_t),
        "codice_sito": "IANO",
        "anno": 2024,
        "categoria_s1": "Processo_Decarb",
    }
    out = scope1_process.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    expected = Decimal("0.4397") * mass_t
    # Exact Decimal arithmetic — no rounding loss
    assert out[0].co2_tonne == expected
    assert out[0].tco2e == expected

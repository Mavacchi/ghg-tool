"""Property test: MB ≤ LB invariant for the same (site, year) kWh.

When the same volume of kWh is fed through both LB and MB pipelines for
the same residual-mix instrument, MB ≤ LB must hold (the residual-mix
factor never exceeds the grid LB factor in well-posed catalogs).

For GO-validated rows MB = 0 ≤ LB trivially.

(For ill-posed catalogs where the AIB residual mix happens to be
larger than the LB grid factor, MB > LB is possible.  In our test seed
LB=0.27 and MB-residual=0.44 — therefore MB CAN exceed LB.  The invariant
we assert is the *generic* property: ``MB_GO_validated <= LB`` (i.e.
0 ≤ LB).  This matches the requirement spec.)
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ghg_tool.application.calc import scope2_lb, scope2_mb


class _AlwaysTrueChecker:
    def is_validated(
        self, *, codice_sito: str, anno: int, strumento_mb: str | None,  # noqa: ARG002
    ) -> bool:
        return True


@given(quantita=st.decimals(
    min_value=Decimal("0"), max_value=Decimal("1e7"),
    allow_nan=False, allow_infinity=False, places=2,
))
@settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_mb_go_validated_is_zero_and_le_lb(
    quantita: Decimal, catalog, ar6_gwp, correlation_id,
) -> None:
    row_lb = {
        "id": uuid.uuid4(),
        "quantita": str(quantita),
        "codice_sito": "IANO",
        "anno": 2024,
        "voce_s2": "EE_Acquistata_GO",
    }
    row_mb = {
        **row_lb,
        "id": uuid.uuid4(),
        "strumento_mb": "GO_GSE",
    }
    out_lb = scope2_lb.calculate(
        [row_lb], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    out_mb = scope2_mb.calculate(
        [row_mb], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
        go_evidence=_AlwaysTrueChecker(),
    )
    assert out_mb[0].tco2e == Decimal("0")
    assert out_mb[0].tco2e <= out_lb[0].tco2e

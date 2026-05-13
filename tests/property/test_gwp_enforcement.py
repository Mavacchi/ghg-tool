"""Property test: GWP enforcement — no mixed AR6/AR5 within a correlation_id.

Generates random ``EmissionRecord`` rows with mixed gwp_set values and
asserts that ``assert_single_gwp_set`` raises ``MixedGWPSetError``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.policies.gwp_enforcement import (
    MixedGWPSetError,
    assert_single_gwp_set,
)


def _make_em(gwp_set: str) -> EmissionRecord:
    return EmissionRecord(
        correlation_id=uuid.uuid4(),
        raw_row_id=None,
        scope=1, sub_scope="combustion",
        codice_sito="IANO", anno=2024,
        tco2e=Decimal("1"),
        factor_id="x", factor_version="v", factor_source="DEFRA",
        gwp_set=gwp_set,
        methodology="activity-based",
        regulatory_stream="CSRD_ESRS_E1"
        if gwp_set == "AR6" else "EU_ETS_PHASE_IV",
        calc_timestamp=datetime.now(UTC),
        created_by="t",
    )


@given(
    n_ar6=st.integers(min_value=1, max_value=10),
    n_ar5=st.integers(min_value=1, max_value=10),
)
def test_mixing_ar6_and_ar5_always_raises(n_ar6: int, n_ar5: int) -> None:
    """Any non-empty mix of AR6 + AR5 → MixedGWPSetError."""
    rows = [_make_em("AR6") for _ in range(n_ar6)] + \
           [_make_em("AR5") for _ in range(n_ar5)]
    import pytest
    with pytest.raises(MixedGWPSetError):
        assert_single_gwp_set([r.gwp_set for r in rows])


@given(
    n=st.integers(min_value=1, max_value=10),
    code=st.sampled_from(["AR6", "AR5"]),
)
def test_uniform_gwp_set_passes(n: int, code: str) -> None:
    """Uniform AR6 or AR5 always passes."""
    rows = [_make_em(code) for _ in range(n)]
    assert assert_single_gwp_set([r.gwp_set for r in rows]) == code

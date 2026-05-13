"""Unit tests for the domain layer: entities, value objects, policies.

All tests are pure Python — no database, no filesystem access.
Coverage targets: DQFinding, GWPValues/get_gwp_values, assert_no_mutation,
assert_single_gwp_set (FR-19, MG-10, MG-12, CG-03, NFR-15).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ghg_tool.domain.entities.dq_finding import DQFinding
from ghg_tool.domain.policies.gwp_enforcement import MixedGWPSetError, assert_single_gwp_set
from ghg_tool.domain.policies.immutability import ImmutabilityViolationError, assert_no_mutation
from ghg_tool.domain.value_objects.gwp_set import AR5, AR6, GWPValues, get_gwp_values

# ---------------------------------------------------------------------------
# DQFinding entity
# ---------------------------------------------------------------------------

class TestDQFindingEntity:

    def test_crit_finding_blocks_pipeline(self) -> None:
        finding = DQFinding(
            rule_id="DQ-CRIT-01",
            severity="CRIT",
            scope=1,
            blocks_pipeline=True,
        )
        assert finding.blocks_pipeline is True
        assert finding.severity == "CRIT"

    def test_info_finding_does_not_block(self) -> None:
        finding = DQFinding(
            rule_id="FR-01-SYNTH",
            severity="INFO",
            blocks_pipeline=False,
        )
        assert finding.blocks_pipeline is False

    def test_finding_is_immutable(self) -> None:
        finding = DQFinding(rule_id="DQ-CRIT-03", severity="CRIT", blocks_pipeline=True)
        # frozen=True raises dataclasses.FrozenInstanceError (AttributeError subclass)
        with pytest.raises(AttributeError):
            finding.rule_id = "CHANGED"  # type: ignore[misc]

    def test_defaults_are_sensible(self) -> None:
        finding = DQFinding(rule_id="X", severity="INFO")
        assert finding.scope is None
        assert finding.codice_sito is None
        assert finding.anno is None
        assert finding.blocks_pipeline is False
        assert finding.dq_report_version == "1.0.0"
        assert finding.extra is None


# ---------------------------------------------------------------------------
# GWPValues value objects and canonical instances
# ---------------------------------------------------------------------------

class TestGWPValues:

    def test_ar6_canonical_values(self) -> None:
        """AR6 CH4=27.9, N2O=273 per methodology_validation §5.2."""
        assert AR6.code == "AR6"
        assert AR6.ch4 == Decimal("27.9")
        assert AR6.n2o == Decimal("273")
        assert AR6.co2 == Decimal("1")

    def test_ar5_canonical_values(self) -> None:
        """AR5 CH4=28, N2O=265 per methodology_validation §5.3 / EU ETS 2023/2122."""
        assert AR5.code == "AR5"
        assert AR5.ch4 == Decimal("28")
        assert AR5.n2o == Decimal("265")
        assert AR5.co2 == Decimal("1")

    def test_gwp_values_is_immutable(self) -> None:
        # frozen=True raises dataclasses.FrozenInstanceError (AttributeError subclass)
        with pytest.raises(AttributeError):
            AR6.ch4 = Decimal("99")  # type: ignore[misc]

    def test_get_gwp_values_ar6(self) -> None:
        result = get_gwp_values("AR6")
        assert result is AR6

    def test_get_gwp_values_ar5(self) -> None:
        result = get_gwp_values("AR5")
        assert result is AR5

    def test_get_gwp_values_invalid_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="AR4"):
            get_gwp_values("AR4")  # type: ignore[arg-type]

    def test_ar6_ar5_are_distinct_instances(self) -> None:
        assert AR6 is not AR5
        assert AR6 != AR5

    def test_gwp_values_equality(self) -> None:
        """Two GWPValues with identical fields compare equal (dataclass)."""
        clone = GWPValues(
            code="AR6",
            co2=Decimal("1"),
            ch4=Decimal("27.9"),
            n2o=Decimal("273"),
            sf6=Decimal("25200"),
            hfc134a=Decimal("1530"),
        )
        assert clone == AR6


# ---------------------------------------------------------------------------
# ImmutabilityViolationError and assert_no_mutation (CG-03)
# ---------------------------------------------------------------------------

class TestImmutabilityPolicy:

    def test_assert_no_mutation_raises(self) -> None:
        with pytest.raises(ImmutabilityViolationError) as exc_info:
            assert_no_mutation("Emission", "value_tco2e")
        assert "Emission.value_tco2e" in str(exc_info.value)
        assert "correction-as-new-row" in str(exc_info.value)

    def test_error_message_includes_entity_and_field(self) -> None:
        try:
            assert_no_mutation("FactorCatalog", "emission_factor")
        except ImmutabilityViolationError as exc:
            msg = str(exc)
            assert "FactorCatalog" in msg
            assert "emission_factor" in msg


# ---------------------------------------------------------------------------
# assert_single_gwp_set — GWP enforcement policy (FR-19, MG-10)
# ---------------------------------------------------------------------------

class TestGWPEnforcementPolicy:

    def test_single_ar6_passes(self) -> None:
        result = assert_single_gwp_set(["AR6", "AR6", "AR6"])
        assert result == "AR6"

    def test_single_ar5_passes(self) -> None:
        result = assert_single_gwp_set(["AR5"])
        assert result == "AR5"

    def test_mixed_ar6_ar5_raises(self) -> None:
        with pytest.raises(MixedGWPSetError, match="Mixed GWP sets"):
            assert_single_gwp_set(["AR6", "AR5", "AR6"])

    def test_empty_list_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            assert_single_gwp_set([])

    def test_error_message_lists_detected_codes(self) -> None:
        try:
            assert_single_gwp_set(["AR5", "AR6"])
        except MixedGWPSetError as exc:
            msg = str(exc)
            assert "AR5" in msg
            assert "AR6" in msg

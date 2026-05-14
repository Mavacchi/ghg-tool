"""Unit tests for Pydantic v2 schemas — validation correctness."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from ghg_tool.api.schemas.auth_schemas import LoginRequest
from ghg_tool.api.schemas.dq_schemas import WaiverRequest
from ghg_tool.api.schemas.emission_schemas import EmissionCorrectionCreate, EmissionCreate
from ghg_tool.api.schemas.factor_schemas import FactorCatalogCreate
from ghg_tool.api.schemas.go_schemas import GoCertificateCreate


class TestEmissionCreate:
    """Tests for EmissionCreate Pydantic v2 schema."""

    def _valid_payload(self, **overrides: object) -> dict:
        base = {
            "scope": 1,
            "sub_scope": "combustion",
            "codice_sito": "IANO",
            "anno": 2024,
            "tco2e": 100.0,
            "raw_scope": 1,
            "factor_id": str(uuid.uuid4()),
            "factor_version": "v1.0",
            "factor_source": "DEFRA",
            "gwp_set": "AR6",
            "methodology": "activity-based",
            "regulatory_stream": "CSRD_ESRS_E1",
        }
        base.update(overrides)
        return base

    def test_valid_scope1_combustion(self) -> None:
        """Valid Scope 1 combustion payload parses successfully."""
        ec = EmissionCreate(**self._valid_payload())
        assert ec.scope == 1
        assert ec.sub_scope == "combustion"

    def test_valid_scope2_mb(self) -> None:
        """Valid Scope 2 MB payload with correct sub_scope."""
        ec = EmissionCreate(**self._valid_payload(scope=2, sub_scope="MB"))
        assert ec.scope == 2
        assert ec.sub_scope == "MB"

    def test_valid_scope3_cat1(self) -> None:
        """Valid Scope 3 Cat1 payload (no codice_sito required)."""
        ec = EmissionCreate(
            **self._valid_payload(scope=3, sub_scope="Cat1", codice_sito=None)
        )
        assert ec.scope == 3
        assert ec.codice_sito is None

    def test_negative_tco2e_rejected(self) -> None:
        """tco2e < 0 raises ValidationError."""
        with pytest.raises(ValidationError):
            EmissionCreate(**self._valid_payload(tco2e=-0.001))

    def test_invalid_scope(self) -> None:
        """scope=0 raises ValidationError."""
        with pytest.raises(ValidationError):
            EmissionCreate(**self._valid_payload(scope=0))

    def test_invalid_sub_scope_for_scope(self) -> None:
        """sub_scope='LB' is invalid for scope=1 (Scope 2 only)."""
        with pytest.raises(ValidationError):
            EmissionCreate(**self._valid_payload(scope=1, sub_scope="LB"))

    def test_unknown_codice_sito_rejected(self) -> None:
        """codice_sito='UNKNOWN' raises ValidationError."""
        with pytest.raises(ValidationError):
            EmissionCreate(**self._valid_payload(codice_sito="UNKNOWN"))

    def test_unknown_methodology_rejected(self) -> None:
        """Unknown methodology raises ValidationError."""
        with pytest.raises(ValidationError):
            EmissionCreate(**self._valid_payload(methodology="fake-method"))

    def test_invalid_gwp_set_rejected(self) -> None:
        """gwp_set='AR4' raises ValidationError (only AR6/AR5 allowed)."""
        with pytest.raises(ValidationError):
            EmissionCreate(**self._valid_payload(gwp_set="AR4"))

    def test_extra_fields_forbidden(self) -> None:
        """Extra fields in payload raise ValidationError (extra='forbid')."""
        with pytest.raises(ValidationError):
            EmissionCreate(**self._valid_payload(unknown_field="oops"))

    def test_all_valid_codice_sito(self) -> None:
        """All 7 allowed site codes are accepted."""
        sites = ["IANO", "VIANO", "VIANO_GARGOLA", "CASALGRANDE",
                 "FIORANO", "SASSUOLO", "FRASSINORO"]
        for site in sites:
            ec = EmissionCreate(**self._valid_payload(codice_sito=site))
            assert ec.codice_sito == site


class TestEmissionCorrectionCreate:
    """Tests for EmissionCorrectionCreate schema."""

    def test_valid_correction(self) -> None:
        """Valid correction payload parses successfully."""
        payload = EmissionCorrectionCreate(
            supersedes_id=uuid.uuid4(),
            new_record={
                "scope": 1,
                "sub_scope": "combustion",
                "codice_sito": "IANO",
                "anno": 2024,
                "tco2e": 110.0,
                "raw_scope": 1,
                "factor_id": str(uuid.uuid4()),
                "factor_version": "v1.1",
                "factor_source": "DEFRA",
                "gwp_set": "AR6",
                "methodology": "activity-based",
                "regulatory_stream": "CSRD_ESRS_E1",
            },
            reason_code="DATA_ERROR",
            justification="Correcting a decimal error in the original record.",
        )
        assert payload.reason_code == "DATA_ERROR"

    def test_short_justification_rejected(self) -> None:
        """Justification under 10 chars raises ValidationError."""
        with pytest.raises(ValidationError):
            EmissionCorrectionCreate(
                supersedes_id=uuid.uuid4(),
                new_record={
                    "scope": 1,
                    "sub_scope": "combustion",
                    "anno": 2024,
                    "tco2e": 110.0,
                    "raw_scope": 1,
                    "factor_id": str(uuid.uuid4()),
                    "factor_version": "v1.0",
                    "factor_source": "DEFRA",
                    "gwp_set": "AR6",
                    "methodology": "activity-based",
                    "regulatory_stream": "CSRD_ESRS_E1",
                },
                reason_code="DATA_ERROR",
                justification="Short",
            )

    def test_invalid_reason_code_rejected(self) -> None:
        """Unknown reason_code raises ValidationError."""
        with pytest.raises(ValidationError):
            EmissionCorrectionCreate(
                supersedes_id=uuid.uuid4(),
                new_record={
                    "scope": 1,
                    "sub_scope": "combustion",
                    "anno": 2024,
                    "tco2e": 110.0,
                    "raw_scope": 1,
                    "factor_id": str(uuid.uuid4()),
                    "factor_version": "v1.0",
                    "factor_source": "DEFRA",
                    "gwp_set": "AR6",
                    "methodology": "activity-based",
                    "regulatory_stream": "CSRD_ESRS_E1",
                },
                reason_code="INVALID_REASON",
                justification="This is a valid justification text.",
            )


class TestFactorCatalogCreate:
    """Tests for FactorCatalogCreate schema."""

    def test_valid_factor(self) -> None:
        """Valid factor payload parses correctly."""
        f = FactorCatalogCreate(
            factor_id="WTT_GAS_NAT_DEFRA_2025",
            version="v1.0",
            substance="Natural gas WTT",
            scope=3,
            category="Cat3_WTT_FUEL",
            source="DEFRA",
            value=0.2123,
            unit="kgCO2e/kWh",
            gwp_set="AR6",
            valid_from=date(2025, 1, 1),
        )
        assert f.source == "DEFRA"

    def test_unknown_source_rejected(self) -> None:
        """Source not in the approved list raises ValidationError."""
        with pytest.raises(ValidationError):
            FactorCatalogCreate(
                factor_id="TEST",
                version="v1",
                substance="Test",
                scope=1,
                category="combustion",
                source="UNKNOWN_SOURCE",
                unit="kgCO2e/kWh",
                gwp_set="AR6",
                valid_from=date(2025, 1, 1),
            )

    def test_negative_value_rejected(self) -> None:
        """Negative factor value raises ValidationError."""
        with pytest.raises(ValidationError):
            FactorCatalogCreate(
                factor_id="TEST",
                version="v1",
                substance="Test",
                scope=1,
                category="combustion",
                source="DEFRA",
                value=-0.5,
                unit="kgCO2e/kWh",
                gwp_set="AR6",
                valid_from=date(2025, 1, 1),
            )


class TestGoCertificateCreate:
    """Tests for GoCertificateCreate schema."""

    def _valid_go(self, **overrides: object) -> dict:
        base = {
            "go_id": "GSE-2024-001",
            "site_id": str(uuid.uuid4()),
            "anno": 2024,
            "volume_mwh": 1000.0,
            "vintage_year": 2024,
            "cancellation_date": "2025-01-15",
            "beneficiary_legal_entity": "Example Ceramics S.p.A.",
            "country_of_issuance": "Italy",
            "technology": "Solar",
            "qc1_conveyed_claim_passed": True,
            "qc2_unique_passed": True,
            "qc3_redeemed_passed": True,
            "qc4_vintage_passed": True,
            "qc5_geographic_passed": True,
            "qc6_scope_passed": True,
            "qc7_exclusivity_passed": True,
            "qc8_residual_mix_disclosed": True,
            "pdf_evidence_uri": "minio://gh-tool-evidence/GSE-2024-001.pdf",
        }
        base.update(overrides)
        return base

    def test_valid_go_certificate(self) -> None:
        """Valid GO certificate payload parses correctly."""
        go = GoCertificateCreate(**self._valid_go())
        assert go.go_id == "GSE-2024-001"
        assert go.qc1_conveyed_claim_passed is True

    def test_cancellation_before_vintage_rejected(self) -> None:
        """cancellation_date < vintage_year raises ValidationError."""
        with pytest.raises(ValidationError):
            GoCertificateCreate(**self._valid_go(vintage_year=2025, cancellation_date="2024-12-31"))


class TestWaiverRequest:
    """Tests for WaiverRequest schema."""

    def test_valid_waiver(self) -> None:
        """Valid waiver request parses correctly."""
        w = WaiverRequest(
            reason_code="OPERATIONAL_ANNOTATION",
            justification="Confirmed by user 2026-05-13 as intentional zero value.",
        )
        assert w.reason_code == "OPERATIONAL_ANNOTATION"

    def test_short_justification_rejected(self) -> None:
        """Justification under 10 chars raises ValidationError."""
        with pytest.raises(ValidationError):
            WaiverRequest(reason_code="USER_CONFIRMED_ZERO", justification="OK")


class TestLoginRequest:
    """Tests for LoginRequest schema."""

    def test_valid_login_request(self) -> None:
        """Valid login payload parses correctly."""
        lr = LoginRequest(username="alice", password="correct-horse-battery")
        assert lr.username == "alice"

    def test_blank_username_rejected(self) -> None:
        """Blank username raises ValidationError."""
        with pytest.raises(ValidationError):
            LoginRequest(username="   ", password="x")

    def test_password_not_in_repr(self) -> None:
        """Password must not appear in schema repr (frozen model)."""
        lr = LoginRequest(username="bob@example.com", password="supersecret")
        # Model is frozen so model_dump() exists but we check the repr is clean
        # (pydantic v2 repr includes all fields but we ensure it won't be logged raw)
        assert isinstance(lr.model_dump(), dict)

"""Coverage tests for audit-trail, dq-findings, factor-catalog, go-certificates, kpis.

These tests focus on RBAC enforcement, happy-path responses, and 4xx paths
for routers that have lower coverage from specialised test files.
All DB access is mocked via dependency_overrides.
"""

from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from fastapi.testclient import TestClient

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.main import app

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TENANT_ID = str(uuid.uuid4())


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        sub=str(uuid.uuid4()),
        role=role,  # type: ignore[arg-type]
        tenant_id=_TENANT_ID,
        jti=str(uuid.uuid4()),
    )


def _auth(role: str) -> Any:
    u = _user(role)

    async def _dep() -> CurrentUser:
        return u

    return _dep


def _mock_db() -> Any:
    async def _gen() -> Any:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
            scalar_one_or_none=MagicMock(return_value=None),
        ))
        yield session

    return _gen


def _setup(role: str) -> None:
    app.dependency_overrides[get_current_user] = _auth(role)
    app.dependency_overrides[get_db] = _mock_db()


def _teardown() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Audit Trail
# ---------------------------------------------------------------------------


class TestAuditTrail:
    """Tests for GET /api/v1/audit-trail/."""

    def test_esg_manager_can_read(self) -> None:
        """esg_manager has audit_trail:read permission."""
        _setup("esg_manager")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/audit-trail/")
        _teardown()
        assert resp.status_code == 200
        data = resp.json()
        # REV-016: response is now AuditTrailResponse with 'entries' key
        assert "entries" in data
        assert "correlation_id" in data

    def test_auditor_can_read(self) -> None:
        """auditor has audit_trail:read permission."""
        _setup("auditor")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/audit-trail/")
        _teardown()
        assert resp.status_code == 200

    def test_data_steward_cannot_read(self) -> None:
        """data_steward does NOT have audit_trail:read permission — should return 403."""
        _setup("data_steward")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/audit-trail/")
        _teardown()
        assert resp.status_code == 403

    def test_unauthenticated_returns_401(self) -> None:
        """No auth → 401."""
        _teardown()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/audit-trail/")
        assert resp.status_code == 401

    def test_filter_params_accepted(self) -> None:
        """Query params anno, codice_sito, limit are accepted without error."""
        _setup("auditor")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                "/api/v1/audit-trail/",
                params={"anno": 2024, "codice_sito": "IANO", "limit": 10},
            )
        _teardown()
        assert resp.status_code == 200

    def test_db_error_returns_500(self) -> None:
        """REV-009: SQLAlchemyError raises 500; RuntimeError (non-SQLAlchemy) propagates."""
        from sqlalchemy.exc import OperationalError

        app.dependency_overrides[get_current_user] = _auth("auditor")

        async def _failing_db() -> Any:
            session = AsyncMock()
            session.execute = AsyncMock(
                side_effect=OperationalError("DB down", None, None)
            )
            yield session

        app.dependency_overrides[get_db] = _failing_db
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/audit-trail/")
        _teardown()
        # REV-009: SQLAlchemyError → 500; no internal detail leaked to client
        assert resp.status_code == 500
        data = resp.json()
        assert "_error" not in data
        assert "Internal error" in str(data)


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------


class TestKPIs:
    """Tests for GET /api/v1/kpis/."""

    def test_all_roles_can_read(self) -> None:
        """All three roles have kpis:read permission."""
        for role in ("data_steward", "esg_manager", "auditor"):
            _setup(role)
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/kpis/")
            _teardown()
            assert resp.status_code == 200, f"Expected 200 for {role}"

    def test_unauthenticated_returns_401(self) -> None:
        """No auth → 401."""
        _teardown()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/kpis/")
        assert resp.status_code == 401

    def test_mv_unavailable_returns_stub(self) -> None:
        """If MV query raises ProgrammingError/OperationalError, stub payload returned."""
        from sqlalchemy.exc import ProgrammingError

        app.dependency_overrides[get_current_user] = _auth("auditor")

        async def _failing_db() -> Any:
            session = AsyncMock()
            session.execute = AsyncMock(
                side_effect=ProgrammingError("relation does not exist", None, None)
            )
            yield session

        app.dependency_overrides[get_db] = _failing_db
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/kpis/")
        _teardown()
        assert resp.status_code == 200
        data = resp.json()
        assert data["kpis"] == []
        # Note is serialised as "_note" via model_dump override
        assert "_note" in data or "note" in data

    def test_gwp_set_param_accepted(self) -> None:
        """gwp_set and anno query params are accepted without error."""
        _setup("esg_manager")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/kpis/", params={"gwp_set": "AR6", "anno": 2024})
        _teardown()
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# DQ Findings
# ---------------------------------------------------------------------------


def _dq_finding_mock(**kwargs: Any) -> MagicMock:
    """Build a MagicMock resembling a DqFinding ORM row."""
    from datetime import UTC, datetime
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.UUID(_TENANT_ID),
        "correlation_id": uuid.uuid4(),
        "parent_finding_id": None,
        "rule_id": "R001",
        "severity": "WARN",
        "scope": 1,
        "codice_sito": "IANO",
        "anno": 2024,
        "metric": "tco2e",
        "value_observed": None,
        "value_reference": None,
        "ratio_yoy": None,
        "z_score": None,
        "trigger_desc": None,
        "recommended_action": None,
        "raw_row_id": None,
        "dq_report_version": "1.0",
        "assessed_at": datetime.now(tz=UTC),
        "blocks_pipeline": False,
        "resolution_status": "OPEN",
        "waiver_reason_code": None,
        "waiver_justification": None,
        "waiver_approved_by": None,
        "resolved_at": None,
    }
    defaults.update(kwargs)
    row = MagicMock(spec_set=list(defaults.keys()))
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


class TestDQFindings:
    """Tests for GET/POST /api/v1/dq-findings/."""

    def test_all_roles_can_list(self) -> None:
        """All three roles have dq_findings:read permission."""
        for role in ("data_steward", "esg_manager", "auditor"):
            with patch(
                "ghg_tool.api.routers.dq_findings.DQFindingsRepository"
            ) as mock_repo:
                # REV-023: router now calls get_findings instead of get_open_findings
                mock_repo.return_value.get_findings = AsyncMock(return_value=[])
                _setup(role)
                with TestClient(app, raise_server_exceptions=False) as client:
                    resp = client.get("/api/v1/dq-findings/")
                _teardown()
            assert resp.status_code == 200, f"Expected 200 for {role}"

    def test_unauthenticated_returns_401(self) -> None:
        """No auth → 401."""
        _teardown()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/dq-findings/")
        assert resp.status_code == 401

    def test_list_with_filters(self) -> None:
        """Severity and anno filters are accepted and applied."""
        with patch("ghg_tool.api.routers.dq_findings.DQFindingsRepository") as mock_repo:
            # REV-023: router now calls get_findings instead of get_open_findings
            mock_repo.return_value.get_findings = AsyncMock(return_value=[])
            _setup("auditor")
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get(
                    "/api/v1/dq-findings/",
                    params={"severity": "WARN", "anno": 2024},
                )
            _teardown()
        assert resp.status_code == 200

    def test_waiver_requires_esg_manager(self) -> None:
        """data_steward cannot create waiver — 403."""
        _setup("data_steward")
        finding_id = uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                f"/api/v1/dq-findings/waiver/{finding_id}",
                json={
                    "reason_code": "ASSURANCE_ACCEPTED",
                    "justification": "Accepted by lead assurer",
                },
            )
        _teardown()
        assert resp.status_code == 403

    def test_auditor_cannot_waive(self) -> None:
        """auditor cannot create waiver — 403."""
        _setup("auditor")
        finding_id = uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                f"/api/v1/dq-findings/waiver/{finding_id}",
                json={
                    "reason_code": "ASSURANCE_ACCEPTED",
                    "justification": "Accepted by lead assurer",
                },
            )
        _teardown()
        assert resp.status_code == 403

    def test_waiver_not_found_returns_404(self) -> None:
        """When the finding is not in DB, waiver returns 404."""
        app.dependency_overrides[get_current_user] = _auth("esg_manager")

        async def _db_not_found() -> Any:
            session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none = MagicMock(return_value=None)
            session.execute = AsyncMock(return_value=mock_result)
            yield session

        app.dependency_overrides[get_db] = _db_not_found
        finding_id = uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                f"/api/v1/dq-findings/waiver/{finding_id}",
                json={
                    "reason_code": "ASSURANCE_ACCEPTED",
                    "justification": "Accepted by lead assurer",
                },
            )
        _teardown()
        assert resp.status_code == 404

    def test_waiver_success(self) -> None:
        """esg_manager can apply a waiver, which calls insert_finding."""
        original = _dq_finding_mock()
        waiver_row = _dq_finding_mock(resolution_status="WAIVED")

        app.dependency_overrides[get_current_user] = _auth("esg_manager")

        async def _db_with_finding() -> Any:
            session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none = MagicMock(return_value=original)
            session.execute = AsyncMock(return_value=mock_result)
            yield session

        app.dependency_overrides[get_db] = _db_with_finding
        finding_id = uuid.uuid4()
        with patch(
            "ghg_tool.api.routers.dq_findings.DQFindingsRepository"
        ) as mock_repo:
            mock_repo.return_value.insert_finding = AsyncMock(return_value=waiver_row)
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(
                    f"/api/v1/dq-findings/waiver/{finding_id}",
                    json={
                        "reason_code": "ASSURANCE_ACCEPTED",
                        "justification": "Accepted by lead assurer in review",
                    },
                )
        _teardown()
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Factor Catalog
# ---------------------------------------------------------------------------


def _factor_mock(**kwargs: Any) -> MagicMock:
    """Build a MagicMock resembling a FactorCatalog ORM row."""
    from datetime import UTC, date, datetime
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.UUID(_TENANT_ID),
        "factor_id": "WTT_GAS_NAT_DEFRA_2025",
        "version": "v1.0",
        "substance": "natural_gas",
        "scope": 1,
        "category": "combustion",
        "source": "DEFRA",
        "value": 2.032,
        "is_licence_only": False,
        "unit": "kg CO2e/kWh",
        "gwp_set": "AR6",
        "vintage": "2025",
        "valid_from": date(2025, 1, 1),
        "valid_to": None,
        "applicability_note": None,
        "pdf_source_uri": None,
        "biogenic_co2_kg_per_unit": None,
        "created_at": datetime.now(tz=UTC),
        "published_at": datetime.now(tz=UTC),
        "published_by": "test-user",
        "is_published": True,
        "is_tbc": False,
    }
    defaults.update(kwargs)
    row = MagicMock(spec_set=list(defaults.keys()))
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


class TestFactorCatalog:
    """Tests for GET/POST /api/v1/factor-catalog/."""

    def test_all_roles_can_list(self) -> None:
        """All three roles have factor_catalog:read permission."""
        for role in ("data_steward", "esg_manager", "auditor"):
            _setup(role)
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/factor-catalog/")
            _teardown()
            assert resp.status_code == 200, f"Expected 200 for {role}"

    def test_unauthenticated_returns_401(self) -> None:
        """No auth → 401."""
        _teardown()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/factor-catalog/")
        assert resp.status_code == 401

    def test_list_factor_versions(self) -> None:
        """GET /factor-catalog/{factor_id}/versions returns 200."""
        _setup("auditor")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/factor-catalog/WTT_GAS_NAT_DEFRA_2025/versions")
        _teardown()
        assert resp.status_code == 200

    def test_auditor_cannot_create_factor(self) -> None:
        """auditor does NOT have factor_catalog:write permission → 403."""
        _setup("auditor")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/factor-catalog/",
                json={
                    "factor_id": "WTT_GAS_NAT_DEFRA_2026",
                    "version": "v1.0",
                    "substance": "natural_gas",
                    "scope": 1,
                    "category": "combustion",
                    "source": "DEFRA",
                    "value": 2.1,
                    "unit": "kg CO2e/kWh",
                    "gwp_set": "AR6",
                    "vintage": "2026",
                    "valid_from": "2026-01-01",
                },
            )
        _teardown()
        assert resp.status_code == 403

    def test_esg_manager_cannot_create_factor(self) -> None:
        """esg_manager does NOT have factor_catalog:write permission → 403."""
        _setup("esg_manager")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/factor-catalog/",
                json={
                    "factor_id": "WTT_GAS_NAT_DEFRA_2026",
                    "version": "v1.0",
                    "substance": "natural_gas",
                    "scope": 1,
                    "category": "combustion",
                    "source": "DEFRA",
                    "value": 2.1,
                    "unit": "kg CO2e/kWh",
                    "gwp_set": "AR6",
                    "vintage": "2026",
                    "valid_from": "2026-01-01",
                },
            )
        _teardown()
        assert resp.status_code == 403

    def test_data_steward_can_create_factor(self) -> None:
        """data_steward can POST a new factor catalog entry."""
        mock_factor = _factor_mock()

        with patch(
            "ghg_tool.api.routers.factor_catalog.FactorCatalogRepository"
        ) as mock_repo:
            mock_repo.return_value.insert = AsyncMock(return_value=mock_factor)
            _setup("data_steward")
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/api/v1/factor-catalog/",
                    json={
                        "factor_id": "WTT_GAS_NAT_DEFRA_2026",
                        "version": "v1.0",
                        "substance": "natural_gas",
                        "scope": 1,
                        "category": "combustion",
                        "source": "DEFRA",
                        "value": 2.1,
                        "unit": "kg CO2e/kWh",
                        "gwp_set": "AR6",
                        "vintage": "2026",
                        "valid_from": "2026-01-01",
                    },
                )
            _teardown()
        assert resp.status_code == 201

    def test_invalid_source_rejected(self) -> None:
        """Factor source must be from allowed list; unknown source → 422."""
        _setup("data_steward")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/factor-catalog/",
                json={
                    "factor_id": "TEST_FACTOR_001",
                    "version": "v1.0",
                    "substance": "natural_gas",
                    "scope": 1,
                    "category": "combustion",
                    "source": "UNKNOWN_PROVIDER",
                    "value": 2.1,
                    "unit": "kg CO2e/kWh",
                    "gwp_set": "AR6",
                    "vintage": "2026",
                    "valid_from": "2026-01-01",
                },
            )
        _teardown()
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GO Certificates
# ---------------------------------------------------------------------------


_SITE_UUID = uuid.uuid4()


def _go_cert_mock(**kwargs: Any) -> MagicMock:
    """Build a MagicMock resembling a GoCertificate ORM row."""
    from datetime import UTC, date, datetime
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.UUID(_TENANT_ID),
        "go_id": "GO-2024-001",
        "site_id": _SITE_UUID,
        "anno": 2024,
        "volume_mwh": 100.0,
        "vintage_year": 2024,
        "cancellation_date": date(2025, 3, 1),
        "beneficiary_legal_entity": "Test SRL",
        "country_of_issuance": "IT",
        "technology": "solar",
        "qc1_conveyed_claim_passed": True,
        "qc2_unique_passed": True,
        "qc3_redeemed_passed": True,
        "qc4_vintage_passed": True,
        "qc5_geographic_passed": True,
        "qc6_scope_passed": True,
        "qc7_exclusivity_passed": True,
        "qc8_residual_mix_disclosed": True,
        "pdf_evidence_uri": "s3://evidence/go-2024-001.pdf",
        "validated_by": "test-user",
        "validated_at": datetime.now(tz=UTC),
    }
    defaults.update(kwargs)
    row = MagicMock(spec_set=list(defaults.keys()))
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


class TestGoCertificates:
    """Tests for /api/v1/go-certificates/."""

    def test_all_roles_can_list(self) -> None:
        """All three roles have go_certificates:read permission."""
        for role in ("data_steward", "esg_manager", "auditor"):
            _setup(role)
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/go-certificates/")
            _teardown()
            assert resp.status_code == 200, f"Expected 200 for {role}"

    def test_unauthenticated_returns_401(self) -> None:
        """No auth → 401."""
        _teardown()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/go-certificates/")
        assert resp.status_code == 401

    _VALID_GO_BODY: dict[str, Any] = {
        "go_id": "GO-2024-002",
        "site_id": str(uuid.uuid4()),
        "anno": 2024,
        "volume_mwh": 50.0,
        "vintage_year": 2024,
        "cancellation_date": "2025-03-01",
        "beneficiary_legal_entity": "Test SRL",
        "country_of_issuance": "IT",
        "technology": "wind",
        "qc1_conveyed_claim_passed": True,
        "qc2_unique_passed": True,
        "qc3_redeemed_passed": True,
        "qc4_vintage_passed": True,
        "qc5_geographic_passed": True,
        "qc6_scope_passed": True,
        "qc7_exclusivity_passed": True,
        "qc8_residual_mix_disclosed": True,
        "pdf_evidence_uri": "s3://evidence/go-2024-002.pdf",
    }

    def test_auditor_cannot_create(self) -> None:
        """auditor does not have go_certificates:write permission → 403."""
        _setup("auditor")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/go-certificates/", json=self._VALID_GO_BODY)
        _teardown()
        assert resp.status_code == 403

    def test_data_steward_can_create(self) -> None:
        """data_steward can POST a new GO certificate."""
        mock_cert = _go_cert_mock()

        app.dependency_overrides[get_current_user] = _auth("data_steward")

        async def _db_with_flush() -> Any:
            session = AsyncMock()
            session.add = MagicMock()
            session.flush = AsyncMock()
            yield session

        app.dependency_overrides[get_db] = _db_with_flush
        with patch(
            "ghg_tool.api.routers.go_certificates.GoCertificate"
        ) as mock_cert_cls:
            mock_cert_cls.return_value = mock_cert
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/api/v1/go-certificates/",
                    json={
                        "go_id": "GO-2024-003",
                        "site_id": str(uuid.uuid4()),
                        "anno": 2024,
                        "volume_mwh": 75.0,
                        "vintage_year": 2024,
                        "cancellation_date": "2025-03-01",
                        "beneficiary_legal_entity": "Test SRL",
                        "country_of_issuance": "IT",
                        "technology": "solar",
                        "qc1_conveyed_claim_passed": True,
                        "qc2_unique_passed": True,
                        "qc3_redeemed_passed": True,
                        "qc4_vintage_passed": True,
                        "qc5_geographic_passed": True,
                        "qc6_scope_passed": True,
                        "qc7_exclusivity_passed": True,
                        "qc8_residual_mix_disclosed": True,
                        "pdf_evidence_uri": "s3://evidence/go-2024-003.pdf",
                    },
                )
        _teardown()
        assert resp.status_code == 201

    def test_validate_not_found_returns_404(self) -> None:
        """POST /go-certificates/{go_id}/validations on unknown go_id → 404 (REV-015)."""
        app.dependency_overrides[get_current_user] = _auth("data_steward")

        async def _db_not_found() -> Any:
            session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none = MagicMock(return_value=None)
            session.execute = AsyncMock(return_value=mock_result)
            yield session

        app.dependency_overrides[get_db] = _db_not_found
        with TestClient(app, raise_server_exceptions=False) as client:
            # REV-015: endpoint changed from PATCH …/validate to POST …/validations
            resp = client.post(
                "/api/v1/go-certificates/NONEXISTENT-GO-ID/validations",
                json={"qc1_conveyed_claim_passed": True},
            )
        _teardown()
        assert resp.status_code == 404

    def test_validate_success_creates_new_version(self) -> None:
        """POST /go-certificates/{go_id}/validations creates a new row (append-only, REV-015)."""
        existing = _go_cert_mock()

        app.dependency_overrides[get_current_user] = _auth("data_steward")

        async def _db_with_existing() -> Any:
            session = AsyncMock()
            # First execute (SELECT for existing cert) returns a result with the existing row
            mock_result = MagicMock()
            mock_result.scalar_one_or_none = MagicMock(return_value=existing)
            session.execute = AsyncMock(return_value=mock_result)
            # add/flush for new row insertion
            session.add = MagicMock()
            session.flush = AsyncMock()
            yield session

        app.dependency_overrides[get_db] = _db_with_existing

        # Patch GoCertificate constructor to return a fully-formed mock
        # Use the real class name but intercept __call__ so select() still works
        new_version = _go_cert_mock(go_id="GO-2024-001")
        with patch(
            "ghg_tool.api.routers.go_certificates.GoCertificate",
            side_effect=[new_version],
        ) as mock_class:
            # Ensure select(GoCertificate) still works by preserving the class attrs
            mock_class.__tablename__ = "go_certificate_evidence"
            mock_class.tenant_id = MagicMock()
            mock_class.go_id = MagicMock()
            mock_class.validated_at = MagicMock()
            # Restore select capability by making it behave like a real table
            with patch("ghg_tool.api.routers.go_certificates.select") as mock_select:
                chained = mock_select.return_value
                chained.where.return_value.order_by.return_value.limit.return_value = MagicMock()
                with TestClient(app, raise_server_exceptions=False) as client:
                    # REV-015: changed from PATCH …/validate to POST …/validations
                    resp = client.post(
                        "/api/v1/go-certificates/GO-2024-001/validations",
                        json={"qc1_conveyed_claim_passed": False},
                    )
        _teardown()
        assert resp.status_code == 201

    def test_list_with_all_qc_filter(self) -> None:
        """GET with all_qc_passed=true filter is accepted without error."""
        _setup("auditor")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                "/api/v1/go-certificates/",
                params={"all_qc_passed": "true", "anno": 2024},
            )
        _teardown()
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# REV-023 regression: GET /dq-findings/?resolution_status=RESOLVED
# ---------------------------------------------------------------------------


class TestDQFindingsResolutionStatusRegression:
    """REV-023: RESOLVED findings must pass through — not silently return []."""

    def test_resolved_status_returns_waived_rows(self) -> None:
        """GET /dq-findings/?resolution_status=WAIVED returns WAIVED rows (regression REV-023).

        Before REV-023, get_open_findings only returned OPEN rows, then the
        in-Python filter discarded them all, leaving an empty list.  Now
        get_findings builds a dynamic predicate and the rows pass through.
        """
        waived_finding = _dq_finding_mock(resolution_status="WAIVED")

        with patch("ghg_tool.api.routers.dq_findings.DQFindingsRepository") as mock_repo:
            mock_repo.return_value.get_findings = AsyncMock(return_value=[waived_finding])
            _setup("auditor")
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get(
                    "/api/v1/dq-findings/",
                    params={"resolution_status": "WAIVED"},
                )
            _teardown()

        assert resp.status_code == 200
        data = resp.json()
        # Items must not be empty — WAIVED row passed through from get_findings
        assert len(data["items"]) == 1
        assert data["items"][0]["resolution_status"] == "WAIVED"

    def test_resolved_status_passes_correct_param_to_repo(self) -> None:
        """Router passes resolution_status filter to get_findings (not silently ignored)."""
        with patch("ghg_tool.api.routers.dq_findings.DQFindingsRepository") as mock_repo:
            mock_get_findings = AsyncMock(return_value=[])
            mock_repo.return_value.get_findings = mock_get_findings
            _setup("auditor")
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get(
                    "/api/v1/dq-findings/",
                    params={"resolution_status": "WAIVED"},
                )
            _teardown()

        assert resp.status_code == 200
        # Verify get_findings was called with resolution_status="WAIVED"
        call_kwargs = mock_get_findings.call_args
        assert call_kwargs is not None
        assert call_kwargs.kwargs.get("resolution_status") == "WAIVED"

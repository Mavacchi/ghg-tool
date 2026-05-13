"""Stubbed integration tests — activated in wave 3 when PostgreSQL is available.

All tests here are marked ``@pytest.mark.integration`` and are skipped
in unit-test CI runs.  When a live DB is available, the ``SQLALCHEMY_URL``
env var must point to the test database.
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestEmissionsIntegration:
    """Integration tests for /api/v1/emissions against a live database."""

    def test_post_emission_inserts_and_is_readable(self) -> None:
        """POST /emissions creates a row that GET /emissions returns."""
        pytest.skip("Requires live PostgreSQL — activate in wave 3")

    def test_delete_emission_returns_405(self) -> None:
        """DELETE /emissions/{id} returns 405 even against a live DB."""
        pytest.skip("Requires live PostgreSQL — activate in wave 3")

    def test_correction_supersedes_original(self) -> None:
        """POST /emissions/correction creates new row and closes predecessor."""
        pytest.skip("Requires live PostgreSQL — activate in wave 3")

    def test_rls_prevents_cross_tenant_access(self) -> None:
        """RLS at DB level blocks cross-tenant row access (SG-02/03)."""
        pytest.skip("Requires live PostgreSQL — activate in wave 3")


@pytest.mark.integration
class TestAuditTrailIntegration:
    """Integration tests for /api/v1/audit-trail."""

    def test_audit_trail_returns_full_lineage(self) -> None:
        """Audit trail row links emission → factor provenance (FR-22)."""
        pytest.skip("Requires live PostgreSQL — activate in wave 3")


@pytest.mark.integration
class TestGoCertificateIntegration:
    """Integration tests for /api/v1/go-certificates."""

    def test_create_and_validate_go_certificate(self) -> None:
        """POST GO cert + PATCH validate creates append-only version chain."""
        pytest.skip("Requires live PostgreSQL — activate in wave 3")

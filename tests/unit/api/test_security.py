"""Unit tests for infrastructure/security modules."""

from __future__ import annotations

import os

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")

from ghg_tool.infrastructure.security.password import hash_password, verify_password
from ghg_tool.infrastructure.security.rbac import (
    PERMISSION_MATRIX,
    ROLE_ADMIN,
    ROLE_EDITOR,
    ROLE_VIEWER,
    is_permitted,
)


class TestPasswordHashing:
    """Tests for bcrypt password hashing (SG-04)."""

    def test_hash_is_not_plaintext(self) -> None:
        """hash_password returns a string that differs from the input."""
        pw = "correct-horse-battery-staple"
        h = hash_password(pw)
        assert h != pw

    def test_verify_correct_password(self) -> None:
        """verify_password returns True for the correct password."""
        pw = "my-secure-pass-2026"
        h = hash_password(pw)
        assert verify_password(pw, h) is True

    def test_verify_wrong_password(self) -> None:
        """verify_password returns False for an incorrect password."""
        h = hash_password("actual-password")
        assert verify_password("wrong-password", h) is False

    def test_bcrypt_hash_starts_with_prefix(self) -> None:
        """bcrypt hashes begin with '$2b$' (bcrypt identifier)."""
        h = hash_password("test")
        assert h.startswith("$2")

    def test_different_hashes_for_same_password(self) -> None:
        """Same plaintext produces different hashes (due to random salt)."""
        pw = "test-password"
        h1 = hash_password(pw)
        h2 = hash_password(pw)
        assert h1 != h2


class TestRBAC:
    """Tests for the RBAC permission matrix (SG-02, FR-31)."""

    def test_editor_can_write_emissions(self) -> None:
        """editor has emissions:write permission."""
        assert is_permitted(ROLE_EDITOR, "emissions", "write") is True

    def test_viewer_cannot_write_emissions(self) -> None:
        """viewer does not have emissions:write permission."""
        assert is_permitted(ROLE_VIEWER, "emissions", "write") is False

    def test_admin_cannot_write_emissions(self) -> None:
        """admin does not have emissions:write permission."""
        assert is_permitted(ROLE_ADMIN, "emissions", "write") is False

    def test_all_roles_can_read_emissions(self) -> None:
        """All three roles can read emissions."""
        for role in [ROLE_EDITOR, ROLE_ADMIN, ROLE_VIEWER]:
            assert is_permitted(role, "emissions", "read") is True

    def test_only_admin_can_waive(self) -> None:
        """Only admin can waive DQ findings."""
        assert is_permitted(ROLE_ADMIN, "dq_findings", "waiver") is True
        assert is_permitted(ROLE_EDITOR, "dq_findings", "waiver") is False
        assert is_permitted(ROLE_VIEWER, "dq_findings", "waiver") is False

    def test_only_admin_can_trigger_pdf(self) -> None:
        """Only admin can trigger PDF reports."""
        assert is_permitted(ROLE_ADMIN, "reports", "pdf") is True
        assert is_permitted(ROLE_EDITOR, "reports", "pdf") is False
        assert is_permitted(ROLE_VIEWER, "reports", "pdf") is False

    def test_viewer_cannot_write_go_certificates(self) -> None:
        """viewer cannot write GO certificates."""
        assert is_permitted(ROLE_VIEWER, "go_certificates", "write") is False
        assert is_permitted(ROLE_VIEWER, "go_certificates", "read") is True

    def test_unknown_role_returns_false(self) -> None:
        """An unknown role always returns False."""
        assert is_permitted("superadmin", "emissions", "read") is False

    def test_unknown_resource_returns_false(self) -> None:
        """An unknown resource always returns False."""
        assert is_permitted(ROLE_EDITOR, "nonexistent_resource", "read") is False

    def test_audit_trail_restricted_to_admin_and_viewer(self) -> None:
        """audit_trail:read is only for admin and viewer."""
        assert is_permitted(ROLE_ADMIN, "audit_trail", "read") is True
        assert is_permitted(ROLE_VIEWER, "audit_trail", "read") is True
        assert is_permitted(ROLE_EDITOR, "audit_trail", "read") is False

    def test_permission_matrix_is_complete(self) -> None:
        """PERMISSION_MATRIX covers all expected resources."""
        expected_resources = {
            "emissions", "kpis", "audit_trail", "factor_catalog",
            "dq_findings", "go_certificates", "reports", "auth",
        }
        assert expected_resources.issubset(set(PERMISSION_MATRIX.keys()))

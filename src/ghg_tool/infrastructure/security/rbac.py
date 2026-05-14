"""RBAC permission matrix — SG-02, FR-31.

Maps (role_code, resource, action) → bool.  This is the application-layer
enforcement; PostgreSQL RLS provides defence-in-depth at the DB layer (AD-008).

Three roles are defined (requirements.md §3):
- ``data_steward``  — ingest, factor catalog, GO QC
- ``esg_manager``   — approve, export, waiver findings, read everything
- ``auditor``       — read-only across all resources

The ``admin`` role is reserved for future use and treated as a superset
of ``esg_manager`` in v1.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Role codes — canonical set matching ref.roles seed data
# ---------------------------------------------------------------------------
ROLE_DATA_STEWARD: Final[str] = "data_steward"
ROLE_ESG_MANAGER: Final[str] = "esg_manager"
ROLE_AUDITOR: Final[str] = "auditor"

ALL_ROLES: Final[frozenset[str]] = frozenset(
    {ROLE_DATA_STEWARD, ROLE_ESG_MANAGER, ROLE_AUDITOR}
)

# ---------------------------------------------------------------------------
# Permission matrix
# Format: { resource: { action: frozenset[role_code] } }
# ---------------------------------------------------------------------------
PERMISSION_MATRIX: Final[dict[str, dict[str, frozenset[str]]]] = {
    "emissions": {
        "read": frozenset({ROLE_DATA_STEWARD, ROLE_ESG_MANAGER, ROLE_AUDITOR}),
        "write": frozenset({ROLE_DATA_STEWARD}),
        "correct": frozenset({ROLE_DATA_STEWARD, ROLE_ESG_MANAGER}),
    },
    "kpis": {
        "read": frozenset({ROLE_DATA_STEWARD, ROLE_ESG_MANAGER, ROLE_AUDITOR}),
    },
    "audit_trail": {
        "read": frozenset({ROLE_ESG_MANAGER, ROLE_AUDITOR}),
    },
    "factor_catalog": {
        "read": frozenset({ROLE_DATA_STEWARD, ROLE_ESG_MANAGER, ROLE_AUDITOR}),
        "write": frozenset({ROLE_DATA_STEWARD}),
        "publish": frozenset({ROLE_ESG_MANAGER}),
        "approve": frozenset({ROLE_ESG_MANAGER}),
    },
    "dq_findings": {
        "read": frozenset({ROLE_DATA_STEWARD, ROLE_ESG_MANAGER, ROLE_AUDITOR}),
        "waiver": frozenset({ROLE_ESG_MANAGER}),
    },
    "go_certificates": {
        "read": frozenset({ROLE_DATA_STEWARD, ROLE_ESG_MANAGER, ROLE_AUDITOR}),
        "write": frozenset({ROLE_DATA_STEWARD}),
        "validate": frozenset({ROLE_DATA_STEWARD}),
    },
    "intensity": {
        "read": frozenset({ROLE_DATA_STEWARD, ROLE_ESG_MANAGER, ROLE_AUDITOR}),
    },
    "reports": {
        "pdf": frozenset({ROLE_ESG_MANAGER}),
        "excel": frozenset({ROLE_DATA_STEWARD, ROLE_ESG_MANAGER}),
        "status": frozenset({ROLE_DATA_STEWARD, ROLE_ESG_MANAGER, ROLE_AUDITOR}),
    },
    "auth": {
        "login": frozenset({ROLE_DATA_STEWARD, ROLE_ESG_MANAGER, ROLE_AUDITOR}),
        "refresh": frozenset({ROLE_DATA_STEWARD, ROLE_ESG_MANAGER, ROLE_AUDITOR}),
    },
    "users": {
        # User management lives behind esg_manager only - the closest thing
        # to an "admin" tier in the current three-role hierarchy. Read/write
        # both require esg_manager so the v1 admin page only exposes user
        # creation + listing to the same role.
        "read": frozenset({ROLE_ESG_MANAGER}),
        "write": frozenset({ROLE_ESG_MANAGER}),
    },
    "reconciliation": {
        # M13 -- CSRD Article 23 restatement workflow.
        # All roles may read snapshots + diffs (auditors need this).
        # Only esg_manager may freeze a new snapshot (privileged action,
        # audit-logged + SIEM-forwarded).
        "read": frozenset({ROLE_DATA_STEWARD, ROLE_ESG_MANAGER, ROLE_AUDITOR}),
        "write": frozenset({ROLE_ESG_MANAGER}),
    },
}


def is_permitted(role: str, resource: str, action: str) -> bool:
    """Check whether *role* may perform *action* on *resource*.

    Args:
        role: The role code from the decoded JWT (e.g. 'data_steward').
        resource: Resource identifier (e.g. 'emissions').
        action: Action identifier (e.g. 'write').

    Returns:
        True if the role is authorised; False otherwise.
    """
    resource_perms = PERMISSION_MATRIX.get(resource, {})
    action_perms = resource_perms.get(action, frozenset())
    return role in action_perms

"""RBAC permission matrix — SG-02, FR-31.

Maps (role_code, resource, action) → bool.  This is the application-layer
enforcement; PostgreSQL RLS provides defence-in-depth at the DB layer (AD-008).

Three roles are defined (requirements.md §3):
- ``editor``  — ingest, factor catalog, GO QC
- ``admin``   — approve, export, waiver findings, read everything
- ``viewer``  — read-only across all resources
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Role codes — canonical set matching ref.roles seed data
# ---------------------------------------------------------------------------
ROLE_EDITOR: Final[str] = "editor"
ROLE_ADMIN: Final[str] = "admin"
ROLE_VIEWER: Final[str] = "viewer"

ALL_ROLES: Final[frozenset[str]] = frozenset(
    {ROLE_EDITOR, ROLE_ADMIN, ROLE_VIEWER}
)

# ---------------------------------------------------------------------------
# Permission matrix
# Format: { resource: { action: frozenset[role_code] } }
# ---------------------------------------------------------------------------
PERMISSION_MATRIX: Final[dict[str, dict[str, frozenset[str]]]] = {
    "emissions": {
        "read": frozenset({ROLE_EDITOR, ROLE_ADMIN, ROLE_VIEWER}),
        "write": frozenset({ROLE_EDITOR}),
        "correct": frozenset({ROLE_EDITOR, ROLE_ADMIN}),
    },
    "kpis": {
        "read": frozenset({ROLE_EDITOR, ROLE_ADMIN, ROLE_VIEWER}),
    },
    "audit_trail": {
        "read": frozenset({ROLE_ADMIN, ROLE_VIEWER}),
    },
    "factor_catalog": {
        "read": frozenset({ROLE_EDITOR, ROLE_ADMIN, ROLE_VIEWER}),
        "write": frozenset({ROLE_EDITOR}),
        "publish": frozenset({ROLE_ADMIN}),
        "approve": frozenset({ROLE_ADMIN}),
    },
    "dq_findings": {
        "read": frozenset({ROLE_EDITOR, ROLE_ADMIN, ROLE_VIEWER}),
        "waiver": frozenset({ROLE_ADMIN}),
    },
    "go_certificates": {
        "read": frozenset({ROLE_EDITOR, ROLE_ADMIN, ROLE_VIEWER}),
        "write": frozenset({ROLE_EDITOR}),
        "validate": frozenset({ROLE_EDITOR}),
    },
    "intensity": {
        "read": frozenset({ROLE_EDITOR, ROLE_ADMIN, ROLE_VIEWER}),
    },
    "reports": {
        "pdf": frozenset({ROLE_ADMIN}),
        "excel": frozenset({ROLE_EDITOR, ROLE_ADMIN}),
        "status": frozenset({ROLE_EDITOR, ROLE_ADMIN, ROLE_VIEWER}),
    },
    "auth": {
        "login": frozenset({ROLE_EDITOR, ROLE_ADMIN, ROLE_VIEWER}),
        "refresh": frozenset({ROLE_EDITOR, ROLE_ADMIN, ROLE_VIEWER}),
    },
    "users": {
        # User management lives behind admin only - the closest thing
        # to an "admin" tier in the current three-role hierarchy. Read/write
        # both require admin so the v1 admin page only exposes user
        # creation + listing to the same role.
        "read": frozenset({ROLE_ADMIN}),
        "write": frozenset({ROLE_ADMIN}),
    },
    "reconciliation": {
        # M13 -- CSRD Article 23 restatement workflow.
        # All roles may read snapshots + diffs (viewers need this).
        # Only admin may freeze a new snapshot (privileged action,
        # audit-logged + SIEM-forwarded).
        "read": frozenset({ROLE_EDITOR, ROLE_ADMIN, ROLE_VIEWER}),
        "write": frozenset({ROLE_ADMIN}),
    },
    "sbti_targets": {
        # M12 -- SBTi-aligned reduction targets (ESRS E1-4).
        # All roles may read targets and trajectories.
        # Only admin may create or deactivate targets.
        "read": frozenset({ROLE_EDITOR, ROLE_ADMIN, ROLE_VIEWER}),
        "write": frozenset({ROLE_ADMIN}),
    },
    "raw_ingestions": {
        # FR-03 Excel bulk import: editor and admin may import.
        # viewer is read-only across the system; no import access.
        "import": frozenset({ROLE_EDITOR, ROLE_ADMIN}),
    },
    "chart_annotations": {
        # M15 -- manual narrative annotations on dashboard charts.
        # All roles read so viewers see the context the team recorded.
        # editor + admin may write (operations team adds
        # context; viewer never modifies the trail).
        "read": frozenset({ROLE_EDITOR, ROLE_ADMIN, ROLE_VIEWER}),
        "write": frozenset({ROLE_EDITOR, ROLE_ADMIN}),
    },
}


def is_permitted(role: str, resource: str, action: str) -> bool:
    """Check whether *role* may perform *action* on *resource*.

    Args:
        role: The role code from the decoded JWT (e.g. 'editor').
        resource: Resource identifier (e.g. 'emissions').
        action: Action identifier (e.g. 'write').

    Returns:
        True if the role is authorised; False otherwise.
    """
    resource_perms = PERMISSION_MATRIX.get(resource, {})
    action_perms = resource_perms.get(action, frozenset())
    return role in action_perms

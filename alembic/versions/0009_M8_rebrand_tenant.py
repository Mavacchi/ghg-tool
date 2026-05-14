"""M8 — Rebrand the default tenant from environment variables.

Reads three optional env vars at upgrade time:

    GHG_TENANT_CODE     — new ref.tenants.code value
    GHG_COMPANY_NAME    — new ref.tenants.legal_name value
    GHG_TENANT_OLD_CODE — code of the row to rebrand
                          (defaults to 'CERAMIC_TILE_CO', the value seeded
                          by the M0 base migration).

If none of the env vars are set, the migration is a no-op so the default
Saturnia-derived tenant remains unchanged. This is reversible: ``downgrade``
restores the M0 defaults.

Revision: 0009_M8
Revises: 0008_M7
"""

from __future__ import annotations

import os

from alembic import op

# ---------------------------------------------------------------------------
revision: str = "0009_M8"
down_revision: str = "0008_M7"
branch_labels: str | None = None
depends_on: str | None = None
# ---------------------------------------------------------------------------

_M0_CODE = "CERAMIC_TILE_CO"
_M0_LEGAL_NAME = "Ceramic Tile Manufacturer S.p.A."


def upgrade() -> None:
    """Apply branding from env vars to the rebranded tenant row."""
    old_code = os.getenv("GHG_TENANT_OLD_CODE", _M0_CODE)
    new_code = os.getenv("GHG_TENANT_CODE")
    new_legal_name = os.getenv("GHG_COMPANY_NAME")

    if not new_code and not new_legal_name:
        # No-op: keep the M0 default branding.
        return

    set_clauses: list[str] = []
    params: dict[str, str] = {"old_code": old_code}
    if new_code:
        set_clauses.append("code = :new_code")
        params["new_code"] = new_code
    if new_legal_name:
        set_clauses.append("legal_name = :new_legal_name")
        params["new_legal_name"] = new_legal_name

    from sqlalchemy import text  # local import — Alembic env already loads SA

    bind = op.get_bind()
    bind.execute(
        text(
            "UPDATE ref.tenants SET "
            + ", ".join(set_clauses)
            + " WHERE code = :old_code"
        ),
        params,
    )


def downgrade() -> None:
    """Restore the M0 default branding on the rebranded tenant."""
    new_code = os.getenv("GHG_TENANT_CODE")
    new_legal_name = os.getenv("GHG_COMPANY_NAME")

    if not new_code and not new_legal_name:
        return

    from sqlalchemy import text

    # Find the rebranded row by matching whichever value(s) we changed.
    match_clauses: list[str] = []
    params: dict[str, str] = {"m0_code": _M0_CODE, "m0_legal_name": _M0_LEGAL_NAME}
    if new_code:
        match_clauses.append("code = :new_code")
        params["new_code"] = new_code
    if new_legal_name:
        match_clauses.append("legal_name = :new_legal_name")
        params["new_legal_name"] = new_legal_name

    bind = op.get_bind()
    bind.execute(
        text(
            "UPDATE ref.tenants "
            "SET code = :m0_code, legal_name = :m0_legal_name "
            "WHERE " + " AND ".join(match_clauses)
        ),
        params,
    )

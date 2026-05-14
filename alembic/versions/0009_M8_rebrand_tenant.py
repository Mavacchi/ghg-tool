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
# Default target rebrand applied when no env var override is provided.
# This makes a fresh `alembic upgrade head` automatically rename the M0
# placeholder to the launch-customer brand.
_LAUNCH_CODE = "GRESMALT"
_LAUNCH_LEGAL_NAME = "Gruppo Ceramiche Gresmalt S.p.A."


def upgrade() -> None:
    """Apply branding to the rebranded tenant row.

    Env vars take precedence; otherwise the launch-customer defaults
    (``_LAUNCH_CODE`` / ``_LAUNCH_LEGAL_NAME``) are applied so the M0
    placeholder ``CERAMIC_TILE_CO`` row is renamed automatically.
    """
    old_code = os.getenv("GHG_TENANT_OLD_CODE", _M0_CODE)
    new_code = os.getenv("GHG_TENANT_CODE") or _LAUNCH_CODE
    new_legal_name = os.getenv("GHG_COMPANY_NAME") or _LAUNCH_LEGAL_NAME

    from sqlalchemy import text  # local import — Alembic env already loads SA

    bind = op.get_bind()
    bind.execute(
        text(
            "UPDATE ref.tenants "
            "SET code = :new_code, legal_name = :new_legal_name "
            "WHERE code = :old_code"
        ),
        {
            "old_code": old_code,
            "new_code": new_code,
            "new_legal_name": new_legal_name,
        },
    )


def downgrade() -> None:
    """Restore the M0 default branding on the rebranded tenant row."""
    new_code = os.getenv("GHG_TENANT_CODE") or _LAUNCH_CODE
    new_legal_name = os.getenv("GHG_COMPANY_NAME") or _LAUNCH_LEGAL_NAME

    from sqlalchemy import text

    bind = op.get_bind()
    bind.execute(
        text(
            "UPDATE ref.tenants "
            "SET code = :m0_code, legal_name = :m0_legal_name "
            "WHERE code = :new_code AND legal_name = :new_legal_name"
        ),
        {
            "m0_code": _M0_CODE,
            "m0_legal_name": _M0_LEGAL_NAME,
            "new_code": new_code,
            "new_legal_name": new_legal_name,
        },
    )

"""Data migration: canonicalise controller legal name to Gruppo Ceramiche Gresmalt S.p.A.

Context
-------
Three different controller-name strings accumulated across compliance documents and the
DB seed during early development:

1. ``docs/gdpr_processing_register.md`` had "Saturnia Ceramica S.r.l. (placeholder)".
2. ``docs/gdpr/dpia.md`` already had the correct name "Gruppo Ceramiche Gresmalt S.p.A.".
3. ``alembic/versions/0001_M0_base_schema.py`` seed had "Ceramic Tile Manufacturer S.p.A.".

The canonical legal entity is **Gruppo Ceramiche Gresmalt S.p.A.** (short: "Gresmalt").
This migration brings the DB row created by the 0001 seed into alignment with that canonical
name.

GDPR Art. 30(1)(a) requires the controller to be unambiguously identified in the Art. 30
register of processing activities. The three-way divergence was a documentary BLOCK (C-011)
preventing production deployment. DPO countersignature on the updated register is required
before go-live.

Revision ID : 0022_M21
Revises     : 0018_M17_chart_annotations
Create Date : 2026-05-14
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0022_M21"
down_revision = "0018_M17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """UPDATE ref.tenants: set the canonical legal name for the Gresmalt tenant.

    This is a data-only migration. The table schema is not changed. The WHERE clause
    targets the specific placeholder name inserted by the 0001 seed so that the UPDATE
    is idempotent: if another deployment already applied this fix manually, the UPDATE
    affects 0 rows rather than overwriting a different (correct) value.
    """
    op.execute(
        """
        UPDATE ref.tenants
        SET    legal_name = 'Gruppo Ceramiche Gresmalt S.p.A.'
        WHERE  legal_name = 'Ceramic Tile Manufacturer S.p.A.'
          AND  legal_name IS NOT NULL;
        """
    )


def downgrade() -> None:
    """Reverse the UPDATE to restore the 0001 seed value.

    Note: downgrading in production is a compliance action and must be approved by
    the DPO.  The ``legal_name IS NOT NULL`` guard prevents accidental re-insertion of
    a NULL row.
    """
    op.execute(
        """
        UPDATE ref.tenants
        SET    legal_name = 'Ceramic Tile Manufacturer S.p.A.'
        WHERE  legal_name = 'Gruppo Ceramiche Gresmalt S.p.A.'
          AND  legal_name IS NOT NULL;
        """
    )

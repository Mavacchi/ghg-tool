"""M13 -- Fix factor_publish_approvals unique constraint (partial, PENDING only).

Problem (documented in wave-2 BackendAgent notes):
  The full UNIQUE (tenant_id, factor_id) on calc.factor_publish_approvals means
  that once a factor's approval row is REJECTED, a second proposal for the same
  factor would violate the constraint -- even though REJECTED rows are immutable
  and therefore cannot be cleaned up without a trigger violation.

Fix:
  1. Drop the full UNIQUE constraint ``uq_fpa_tenant_factor``.
  2. Create a PARTIAL UNIQUE INDEX scoped to ``decision = 'PENDING'`` rows only.

Result:
  - REJECTED (and APPROVED) rows remain in history permanently as required
    by ISAE 3000 / CSRD ESRS 1 §85 append-only immutability.
  - A new PENDING proposal for the same factor is allowed after a REJECTED one.
  - There is still at most one PENDING row per (tenant_id, factor_id) at any
    given time, preserving the two-eyes workflow invariant.

Revision: 0014_M13
Revises: 0013_M12
"""

from __future__ import annotations

from alembic import op

# ---------------------------------------------------------------------------
revision: str = "0014_M13"
down_revision: str = "0013_M12"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA = "calc"
_TABLE = "factor_publish_approvals"
_OLD_CONSTRAINT = "uq_fpa_tenant_factor"
_NEW_INDEX = "uq_fpa_tenant_factor_pending"
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Replace full UNIQUE with partial UNIQUE scoped to PENDING rows."""

    # Drop the original full unique constraint added in M11.
    op.drop_constraint(
        _OLD_CONSTRAINT,
        _TABLE,
        schema=_SCHEMA,
        type_="unique",
    )

    # Partial unique: only one PENDING proposal per (tenant_id, factor_id).
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_NEW_INDEX}
            ON {_SCHEMA}.{_TABLE} (tenant_id, factor_id)
            WHERE decision = 'PENDING';
        """
    )


def downgrade() -> None:
    """Restore the original full UNIQUE constraint."""
    op.execute(
        f"DROP INDEX IF EXISTS {_SCHEMA}.{_NEW_INDEX};"
    )
    op.create_unique_constraint(
        _OLD_CONSTRAINT,
        _TABLE,
        ["tenant_id", "factor_id"],
        schema=_SCHEMA,
    )

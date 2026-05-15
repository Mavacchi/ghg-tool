"""Merge heads: 0022_M21 (tenant_name_reconcile) + 0023_M22 (calc_runs_append_only).

Context
-------
Two parallel migration branches accumulated on ``claude/fix-auth-validation-Uea6O``:

1. ``0022_M21_tenant_name_reconcile`` (down=0018_M17) — pre-existing wave-4 fix for
   the controller legal name, predates the Q1.A dual-track work.
2. ``0023_M22_calc_runs_append_only`` (down=0021_M20) — adds the append-only triggers
   to ``ops.calc_runs`` per compliance Q2 decision.

Alembic ``upgrade head`` fails with multiple heads. This is a metadata-only merge
revision: it has no schema operations of its own; it only declares that the two
branches converge here so subsequent migrations can build on a single head.

Revision ID : 0024_M23
Revises     : 0022_M21, 0023_M22
Create Date : 2026-05-15
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0024_M23"
down_revision: str | Sequence[str] = ("0022_M21", "0023_M22")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No schema change — pure merge of two parallel revision branches."""


def downgrade() -> None:
    """No schema change — pure merge of two parallel revision branches."""

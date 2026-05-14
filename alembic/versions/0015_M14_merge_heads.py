"""M14 -- merge multi-head: 0012_M11 + 0014_M13.

Two parallel branches were created in the wave-2 wave when two agents
landed migrations off the same parent (0011_M10) without coordinating:

  - 0012_M11 (factor_publish_approvals)        --> orphan branch
  - 0012_M13 (report_snapshots) -> 0013_M12 (sbti_targets)
                                -> 0014_M13 (fpa_partial_unique)

``alembic upgrade head`` would now refuse with "Multiple heads detected".
This migration is a no-op merge that re-unifies the two heads so the
linear chain resumes from a single tip.

Both upgrade() and downgrade() are intentionally empty: we are only
recording the topology, not changing any schema object.

Revision: 0015_M14
Revises: 0012_M11, 0014_M13
"""

from __future__ import annotations

from alembic import op  # noqa: F401  (kept for API parity; not used)

# ---------------------------------------------------------------------------
revision: str = "0015_M14"
down_revision: tuple[str, str] = ("0012_M11", "0014_M13")
branch_labels: str | None = None
depends_on: str | None = None
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """No-op: merge both heads into a single linear chain.

    No schema objects are created or modified. Both predecessors have
    already done their work; we just need a single revision tip so
    Alembic stops complaining about multiple heads.
    """


def downgrade() -> None:
    """No-op: split back into the two parallel heads.

    Reverses the merge by restoring the multi-head topology.
    """

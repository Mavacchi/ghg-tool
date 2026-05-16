"""M12 — GDPR Art. 17 erasure: add erased_at column to ref.users.

Adds a nullable TIMESTAMP WITH TIME ZONE column ``erased_at`` to ``ref.users``
to record the moment when a user's PII was pseudonymised via the
``DELETE /api/v1/users/{user_id}`` endpoint (GDPR Art. 17 right to erasure).

Design decisions:
  - The column is NULL for non-erased users.
  - A non-NULL ``erased_at`` combined with ``password_hash = '!erased'`` and
    ``is_active = FALSE`` is the canonical signal that a row has been erased.
  - The user row is NEVER deleted: audit_log FK ``user_id`` must remain valid
    for the 10-year CSRD Art. 23(2) retention period.
  - No trigger is added on this column; the API layer (users.py erase_user)
    is responsible for atomically updating all PII fields + ``erased_at``.

Coordination with cluster METHOD:
  - This worktree's migration head before this revision was ``0028_M8``.
  - If METHOD cluster adds migrations 0029-0031 later, a merge head will be
    required.  The GDPR cluster owns revision ``0029_M12``; METHOD should use
    ``0030_M*`` or higher to avoid collision.

Revision: 0029_M12
Down revision: 0028_M8 (head of this worktree at time of writing)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# ---------------------------------------------------------------------------
# Alembic revision metadata
# ---------------------------------------------------------------------------

revision: str = "0029_M12"
down_revision: str = "0028_M8"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Add erased_at TIMESTAMPTZ column to ref.users."""
    op.add_column(
        "users",
        sa.Column(
            "erased_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "GDPR Art. 17 erasure timestamp — set when the user row is "
                "pseudonymised via DELETE /api/v1/users/{id}.  NULL means the "
                "user has not been erased.  The user row is never deleted so "
                "that audit_log.user_id FK remains valid for 10 years (CSRD "
                "Art. 23(2))."
            ),
        ),
        schema="ref",
    )


def downgrade() -> None:
    """Remove erased_at column from ref.users."""
    op.drop_column("users", "erased_at", schema="ref")

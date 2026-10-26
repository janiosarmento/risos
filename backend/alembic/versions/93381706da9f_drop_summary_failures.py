"""drop the summary_failures table

Nothing has written to it since 2ea5475 (2026-04-03), when API errors stopped
being recorded as failures; its last rows date from that day. It was only read
for a stale count on the status endpoint and cleared by reprocess-summary.

Revision ID: 93381706da9f
Revises: e5f8b3d0c2a4
Create Date: 2026-10-26

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "93381706da9f"
down_revision = "e5f8b3d0c2a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_failures_hash")
    op.execute("DROP TABLE IF EXISTS summary_failures")


def downgrade() -> None:
    # Recreates the empty table; the dropped rows are not restored.
    op.create_table(
        "summary_failures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_failures_hash", "summary_failures", ["content_hash"])

"""drop unused feed columns and the cleanup_logs table

- Feed.allow_duplicate_urls: no API or UI ever set it (0 on every feed).
- Feed.last_error_at: written on fetch errors, never read.
- cleanup_logs: one row per retention cleanup, never read; the cleanup job
  already logs the same counts.

Revision ID: cb61cb70725b
Revises: 93381706da9f
Create Date: 2026-10-26

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "cb61cb70725b"
down_revision = "93381706da9f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("feeds") as batch_op:
        batch_op.drop_column("allow_duplicate_urls")
        batch_op.drop_column("last_error_at")

    op.execute("DROP INDEX IF EXISTS idx_cleanup_executed")
    op.execute("DROP TABLE IF EXISTS cleanup_logs")


def downgrade() -> None:
    # Recreates the schema only; dropped values and log rows are not restored.
    with op.batch_alter_table("feeds") as batch_op:
        batch_op.add_column(sa.Column("last_error_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("allow_duplicate_urls", sa.Boolean(), nullable=True)
        )

    op.create_table(
        "cleanup_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column("posts_removed", sa.Integer(), nullable=True),
        sa.Column("full_content_cleared", sa.Integer(), nullable=True),
        sa.Column("summaries_cleared", sa.Integer(), nullable=True),
        sa.Column("unread_removed", sa.Integer(), nullable=True),
        sa.Column("bytes_freed", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_cleanup_executed", "cleanup_logs", ["executed_at"])

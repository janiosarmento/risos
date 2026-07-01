"""drop_orphan_feed_post_cleanup_columns

Remove columns that were never read or written from application code:

- Feed.disabled_at / Feed.disable_reason — leftover from auto-disable
  scaffolding removed in commit 2fcccfd.
- Post.fetch_full_attempted_at — never read or written.
- CleanupLog.notes — never written.

These are dead schema — no application code references them, no data
loss to worry about.  (REFACTOR.md Y2)

Revision ID: 107c9e4c7820
Revises: e5f6g7h8i9j0
Create Date: 2026-07-01 20:09:05.439212

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "107c9e4c7820"
down_revision: Union[str, Sequence[str], None] = "e5f6g7h8i9j0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("feeds") as batch_op:
        batch_op.drop_column("disabled_at")
        batch_op.drop_column("disable_reason")

    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_column("fetch_full_attempted_at")

    with op.batch_alter_table("cleanup_logs") as batch_op:
        batch_op.drop_column("notes")


def downgrade() -> None:
    with op.batch_alter_table("feeds") as batch_op:
        batch_op.add_column(sa.Column("disabled_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("disable_reason", sa.Text(), nullable=True))

    with op.batch_alter_table("posts") as batch_op:
        batch_op.add_column(sa.Column("fetch_full_attempted_at", sa.DateTime(), nullable=True))

    with op.batch_alter_table("cleanup_logs") as batch_op:
        batch_op.add_column(sa.Column("notes", sa.Text(), nullable=True))

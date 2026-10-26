"""delete post_tags and summary_queue rows of deleted posts

Revision ID: a7d2e9c41f03
Revises: cb61cb70725b
Create Date: 2026-10-26

Retention's bulk post delete used to skip the ORM cascade, leaving rows
that point at posts that no longer exist.
"""

from alembic import op

revision = "a7d2e9c41f03"
down_revision = "cb61cb70725b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("post_tags", "summary_queue"):
        op.execute(
            f"DELETE FROM {table} "
            "WHERE NOT EXISTS (SELECT 1 FROM posts WHERE posts.id = post_id)"
        )


def downgrade() -> None:
    pass

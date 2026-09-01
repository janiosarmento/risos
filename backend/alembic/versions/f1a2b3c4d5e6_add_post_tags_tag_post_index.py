"""add composite index post_tags(tag, post_id)

Topic sidebar counts (list_topics) aggregate post_tags by tag and join
posts for the unread flag. With only a single-column index on `tag`,
SQLite planned the query from `posts.is_read` and probed post_tags row by
row, taking ~23s on the production DB. A covering (tag, post_id) index
lets the aggregate be driven by tag and cuts it to a few seconds.

Revision ID: f1a2b3c4d5e6
Revises: 107c9e4c7820
Create Date: 2026-08-31 23:05:00.000000

"""
from typing import Sequence, Union

from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "107c9e4c7820"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "idx_post_tags_tag_post"


def _has_index(name: str, table: str) -> bool:
    bind = op.get_bind()
    existing = {ix["name"] for ix in inspect(bind).get_indexes(table)}
    return name in existing


def upgrade() -> None:
    if not _has_index(INDEX_NAME, "post_tags"):
        op.create_index(
            INDEX_NAME, "post_tags", ["tag", "post_id"], unique=False
        )


def downgrade() -> None:
    if _has_index(INDEX_NAME, "post_tags"):
        op.drop_index(INDEX_NAME, table_name="post_tags")

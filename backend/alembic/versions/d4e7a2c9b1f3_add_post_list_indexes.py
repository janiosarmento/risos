"""add post list indexes: (feed_id, sort_date) and keep_unread

A feed's post list filters on feed_id and orders by sort_date. With only a
single-column feed_id index SQLite sorted every post of the feed in a temp
B-tree before taking a page (~330ms cold on a 24k-post feed); the composite
index walks the feed in order and stops after the page. It also covers every
lookup the old feed_id index served, so that one is dropped.

The keep_unread count runs on every post list request and was a full table
scan. The partial index's WHERE is written as `IS 1` because that is what
SQLAlchemy emits for `.is_(True)`, and SQLite only uses a partial index when
the query repeats its WHERE term exactly (`= 1` is not used for `IS 1`).

Revision ID: d4e7a2c9b1f3
Revises: c3f9a1b7d5e2
Create Date: 2026-10-25

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "d4e7a2c9b1f3"
down_revision = "c3f9a1b7d5e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_posts_feed_sort ON posts (feed_id, sort_date)"
    )
    op.execute("DROP INDEX IF EXISTS idx_posts_feed")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_posts_keep_unread ON posts (keep_unread) "
        "WHERE keep_unread IS 1"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_posts_keep_unread")
    op.execute("CREATE INDEX IF NOT EXISTS idx_posts_feed ON posts (feed_id)")
    op.execute("DROP INDEX IF EXISTS idx_posts_feed_sort")

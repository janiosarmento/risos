"""recreate starred/suggested/read_at partial indexes with `IS 1`

These were created as `WHERE x = 1`, but SQLAlchemy emits `x IS 1` for
`.is_(True)`, and SQLite only uses a partial index when the query repeats the
index's WHERE term exactly. So the starred count was a full table scan, and
the suggested and retention queries fell back to the is_read index.
idx_posts_liked is left alone: every is_liked query is written `= 1`.

Revision ID: e5f8b3d0c2a4
Revises: d4e7a2c9b1f3
Create Date: 2026-10-25

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "e5f8b3d0c2a4"
down_revision = "d4e7a2c9b1f3"
branch_labels = None
depends_on = None

# name -> (indexed column, column tested by the partial index's WHERE)
INDEXES = {
    "idx_posts_starred": ("is_starred", "is_starred"),
    "idx_posts_suggested": ("is_suggested", "is_suggested"),
    "idx_posts_read_at": ("read_at", "is_read"),
}


def _recreate(operator: str) -> None:
    for name, (column, flag) in INDEXES.items():
        op.execute(f"DROP INDEX IF EXISTS {name}")
        op.execute(
            f"CREATE INDEX {name} ON posts ({column}) WHERE {flag} {operator} 1"
        )


def upgrade() -> None:
    _recreate("IS")


def downgrade() -> None:
    _recreate("=")

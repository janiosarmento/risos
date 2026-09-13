"""add curation_cache table

Curation results are expensive to produce (an LLM round-trip) and depend
only on the exact set of posts analyzed, so they memoize cleanly. The key
is a hash of the filter context, language, and sorted post ids: star or
unstar anything and the key changes, so a stale row is never read rather
than needing explicit invalidation.

Revision ID: a7c1d2e3f4b5
Revises: f1a2b3c4d5e6
Create Date: 2026-09-13 16:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c1d2e3f4b5"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "curation_cache"


def _has_table(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _has_table(TABLE_NAME):
        op.create_table(
            TABLE_NAME,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("scope_key", sa.Text(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("scope_key", name="uq_curation_cache_scope_key"),
        )


def downgrade() -> None:
    if _has_table(TABLE_NAME):
        op.drop_table(TABLE_NAME)

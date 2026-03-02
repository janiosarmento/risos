"""add_topics

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    # Check existing tables
    tables = [row[0] for row in conn.execute(sa.text(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ))]

    if 'topics' not in tables:
        op.create_table(
            'topics',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('name', sa.Text(), nullable=False, unique=True),
            sa.Column('position', sa.Integer(), server_default='0'),
            sa.Column('created_at', sa.Text(), server_default=sa.text("(datetime('now'))")),
        )

    if 'topic_tags' not in tables:
        op.create_table(
            'topic_tags',
            sa.Column('topic_id', sa.Integer(), sa.ForeignKey('topics.id', ondelete='CASCADE'), nullable=False),
            sa.Column('tag', sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint('topic_id', 'tag'),
        )

        op.create_index('idx_topic_tags_tag', 'topic_tags', ['tag'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_topic_tags_tag', table_name='topic_tags')
    op.drop_table('topic_tags')
    op.drop_table('topics')

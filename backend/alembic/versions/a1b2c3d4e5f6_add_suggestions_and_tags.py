"""add_suggestions_and_tags

Revision ID: a1b2c3d4e5f6
Revises: 73152e004d90
Create Date: 2026-01-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '73152e004d90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    # Check existing columns in posts table
    columns = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(posts)"))]

    # Add is_liked column
    if 'is_liked' not in columns:
        op.add_column('posts', sa.Column('is_liked', sa.Integer(), nullable=True, server_default='0'))

    # Add liked_at column
    if 'liked_at' not in columns:
        op.add_column('posts', sa.Column('liked_at', sa.Text(), nullable=True))

    # Add is_suggested column
    if 'is_suggested' not in columns:
        op.add_column('posts', sa.Column('is_suggested', sa.Integer(), nullable=True, server_default='0'))

    # Add suggestion_score column
    if 'suggestion_score' not in columns:
        op.add_column('posts', sa.Column('suggestion_score', sa.Float(), nullable=True))

    # Add suggested_at column
    if 'suggested_at' not in columns:
        op.add_column('posts', sa.Column('suggested_at', sa.Text(), nullable=True))

    # Check existing indexes
    indexes = [row[1] for row in conn.execute(sa.text("PRAGMA index_list(posts)"))]

    # Create index for liked posts
    if 'idx_posts_liked' not in indexes:
        op.create_index(
            'idx_posts_liked',
            'posts',
            ['is_liked'],
            unique=False,
            sqlite_where=sa.text('is_liked = 1')
        )

    # Create index for suggested posts
    if 'idx_posts_suggested' not in indexes:
        op.create_index(
            'idx_posts_suggested',
            'posts',
            ['is_suggested'],
            unique=False,
            sqlite_where=sa.text('is_suggested = 1')
        )

    # Check if post_tags table exists
    tables = [row[0] for row in conn.execute(sa.text(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ))]

    if 'post_tags' not in tables:
        op.create_table(
            'post_tags',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('post_id', sa.Integer(), sa.ForeignKey('posts.id', ondelete='CASCADE'), nullable=False),
            sa.Column('tag', sa.Text(), nullable=False),
            sa.Column('created_at', sa.Text(), server_default=sa.text("(datetime('now'))")),
            sa.UniqueConstraint('post_id', 'tag', name='uq_post_tag')
        )

        op.create_index('idx_post_tags_tag', 'post_tags', ['tag'], unique=False)
        op.create_index('idx_post_tags_post_id', 'post_tags', ['post_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_post_tags_post_id', table_name='post_tags')
    op.drop_index('idx_post_tags_tag', table_name='post_tags')
    op.drop_table('post_tags')

    op.drop_index('idx_posts_suggested', table_name='posts')
    op.drop_index('idx_posts_liked', table_name='posts')

    op.drop_column('posts', 'suggested_at')
    op.drop_column('posts', 'suggestion_score')
    op.drop_column('posts', 'is_suggested')
    op.drop_column('posts', 'liked_at')
    op.drop_column('posts', 'is_liked')

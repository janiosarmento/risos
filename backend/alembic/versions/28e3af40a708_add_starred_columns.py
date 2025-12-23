"""add_starred_columns

Revision ID: 28e3af40a708
Revises: 172dd9c19d31
Create Date: 2025-12-23 19:45:59.377989

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28e3af40a708'
down_revision: Union[str, Sequence[str], None] = '172dd9c19d31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    # Check if columns exist before adding (for databases that were manually updated)
    columns = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(posts)"))]

    if 'is_starred' not in columns:
        op.add_column('posts', sa.Column('is_starred', sa.Boolean(), nullable=True, server_default='0'))

    if 'starred_at' not in columns:
        op.add_column('posts', sa.Column('starred_at', sa.DateTime(), nullable=True))

    # Check if index exists before creating
    indexes = [row[1] for row in conn.execute(sa.text("PRAGMA index_list(posts)"))]

    if 'idx_posts_starred' not in indexes:
        op.create_index(
            'idx_posts_starred',
            'posts',
            ['is_starred'],
            unique=False,
            sqlite_where=sa.text('is_starred = 1')
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_posts_starred', table_name='posts')
    op.drop_column('posts', 'starred_at')
    op.drop_column('posts', 'is_starred')

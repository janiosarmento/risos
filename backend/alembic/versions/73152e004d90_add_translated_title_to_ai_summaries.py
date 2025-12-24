"""add_translated_title_to_ai_summaries

Revision ID: 73152e004d90
Revises: 28e3af40a708
Create Date: 2025-12-24 13:01:21.403889

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '73152e004d90'
down_revision: Union[str, Sequence[str], None] = '28e3af40a708'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('ai_summaries', sa.Column('translated_title', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('ai_summaries', 'translated_title')

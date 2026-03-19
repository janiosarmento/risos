"""add_keep_unread

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6g7h8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6g7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    columns = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(posts)"))]

    if "keep_unread" not in columns:
        op.add_column(
            "posts",
            sa.Column(
                "keep_unread",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("posts", "keep_unread")

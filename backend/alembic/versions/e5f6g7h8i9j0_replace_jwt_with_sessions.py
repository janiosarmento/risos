"""Replace JWT auth with session cookie auth

Revision ID: e5f6g7h8i9j0
Revises: a43f7a90238c
Create Date: 2026-06-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e5f6g7h8i9j0"
down_revision: Union[str, Sequence[str], None] = "a43f7a90238c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Create user_sessions table
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_session_expires", "user_sessions", ["expires_at"])

    # Drop token_blacklist table
    op.drop_index("idx_blacklist_expires", table_name="token_blacklist")
    op.drop_table("token_blacklist")


def downgrade():
    # Restore token_blacklist
    op.create_table(
        "token_blacklist",
        sa.Column("jti", sa.Text(), primary_key=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_blacklist_expires", "token_blacklist", ["expires_at"])

    # Drop user_sessions
    op.drop_index("idx_session_expires", table_name="user_sessions")
    op.drop_table("user_sessions")

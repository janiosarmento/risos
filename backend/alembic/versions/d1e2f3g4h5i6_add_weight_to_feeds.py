"""add weight to feeds

Revision ID: d1e2f3g4h5i6
Revises: c3d4e5f6g7h8
Create Date: 2026-05-13

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d1e2f3g4h5i6"
down_revision = "c3d4e5f6g7h8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "feeds",
        sa.Column("weight", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("feeds", "weight")

"""add excluded_audience to ai_summaries

Revision ID: b8d2e4f6a1c3
Revises: a7c1d2e3f4b5
Create Date: 2026-10-07

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b8d2e4f6a1c3"
down_revision = "a7c1d2e3f4b5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ai_summaries",
        sa.Column("excluded_audience", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("ai_summaries", "excluded_audience")

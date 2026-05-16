"""Rename cerebras pref keys to ai

Revision ID: a43f7a90238c
Revises: d1e2f3g4h5i6
Create Date: 2026-05-16

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a43f7a90238c"
down_revision = "d1e2f3g4h5i6"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE app_settings SET key = 'pref_ai_model' WHERE key = 'pref_cerebras_model'"
    )
    op.execute(
        "UPDATE app_settings SET key = 'pref_ai_api_keys' WHERE key = 'pref_cerebras_api_keys'"
    )


def downgrade():
    op.execute(
        "UPDATE app_settings SET key = 'pref_cerebras_model' WHERE key = 'pref_ai_model'"
    )
    op.execute(
        "UPDATE app_settings SET key = 'pref_cerebras_api_keys' WHERE key = 'pref_ai_api_keys'"
    )

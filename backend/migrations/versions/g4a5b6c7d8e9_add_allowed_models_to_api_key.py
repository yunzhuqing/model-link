"""add allowed_models to api_key

Revision ID: g4a5b6c7d8e9
Revises: f3a4b5c6d7e8
Create Date: 2026-04-14 20:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'g4a5b6c7d8e9'
down_revision = 'f3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ml_api_keys', sa.Column('allowed_models', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('ml_api_keys', 'allowed_models')

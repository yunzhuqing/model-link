"""add is_active to model

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-04-14 18:25:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3a4b5c6d7e8'
down_revision = 'e2f3a4b5c6d7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ml_models', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')))


def downgrade():
    op.drop_column('ml_models', 'is_active')

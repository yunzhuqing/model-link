"""add is_active to provider

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-14 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e2f3a4b5c6d7'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ml_providers', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')))


def downgrade():
    op.drop_column('ml_providers', 'is_active')

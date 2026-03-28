"""add pricing_tiers to ml_models

Revision ID: l8m9n0o1p2q3
Revises: k7l8m9n0o1p2
Create Date: 2026-03-28

"""
from alembic import op
import sqlalchemy as sa

revision = 'l8m9n0o1p2q3'
down_revision = 'k7l8m9n0o1p2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ml_models',
        sa.Column('pricing_tiers', sa.JSON(), nullable=True)
    )


def downgrade():
    op.drop_column('ml_models', 'pricing_tiers')

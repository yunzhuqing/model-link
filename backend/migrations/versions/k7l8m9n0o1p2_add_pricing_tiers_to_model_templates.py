"""add pricing_tiers to ml_model_templates

Revision ID: k7l8m9n0o1p2
Revises: j6k7l8m9n0o1
Create Date: 2026-03-28

"""
from alembic import op
import sqlalchemy as sa

revision = 'k7l8m9n0o1p2'
down_revision = 'j6k7l8m9n0o1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ml_model_templates',
        sa.Column('pricing_tiers', sa.JSON(), nullable=True)
    )


def downgrade():
    op.drop_column('ml_model_templates', 'pricing_tiers')

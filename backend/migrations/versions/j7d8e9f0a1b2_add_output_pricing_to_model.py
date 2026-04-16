"""add output_pricing to model and model_template

Revision ID: j7d8e9f0a1b2
Revises: i6c7d8e9f0a1
Create Date: 2025-04-15 21:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'j7d8e9f0a1b2'
down_revision = 'i6c7d8e9f0a1'
branch_labels = None
depends_on = None


def upgrade():
    # Add output_pricing JSON column to ml_models
    op.add_column('ml_models', sa.Column('output_pricing', sa.JSON(), nullable=True))

    # Add output_pricing JSON column to ml_model_templates
    op.add_column('ml_model_templates', sa.Column('output_pricing', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('ml_model_templates', 'output_pricing')
    op.drop_column('ml_models', 'output_pricing')

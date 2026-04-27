"""Add timeout field to ml_models and ml_model_templates

Revision ID: s6f7g8h9i0j1
Revises: r5e6f7g8h9i0
Create Date: 2025-04-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 's6f7g8h9i0j1'
down_revision = 'r5e6f7g8h9i0'
branch_labels = None
depends_on = None


def upgrade():
    # Add timeout column to ml_models
    op.add_column('ml_models', sa.Column('timeout', sa.Integer(), nullable=True, default=None))
    # Add timeout column to ml_model_templates
    op.add_column('ml_model_templates', sa.Column('timeout', sa.Integer(), nullable=True, default=None))


def downgrade():
    op.drop_column('ml_models', 'timeout')
    op.drop_column('ml_model_templates', 'timeout')

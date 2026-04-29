"""Add priority and traffic_ratio columns to ml_models

Revision ID: t6g7h8i9j0k1
Revises: s6f7g8h9i0j1
Create Date: 2026-04-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 't6g7h8i9j0k1'
down_revision = 's6f7g8h9i0j1'
branch_labels = None
depends_on = None


def upgrade():
    # Add priority column to ml_models
    op.add_column('ml_models', sa.Column('priority', sa.Integer(), nullable=False, server_default='0'))
    # Add traffic_ratio column to ml_models
    op.add_column('ml_models', sa.Column('traffic_ratio', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('ml_models', 'traffic_ratio')
    op.drop_column('ml_models', 'priority')
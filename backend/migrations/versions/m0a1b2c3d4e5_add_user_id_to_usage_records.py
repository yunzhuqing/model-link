"""add user_id to usage records

Revision ID: m0a1b2c3d4e5
Revises: l9f0a1b2c3d4
Create Date: 2026-04-18 16:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'm0a1b2c3d4e5'
down_revision = 'l9f0a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ml_usage_records', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_index('ix_ml_usage_records_user_id', 'ml_usage_records', ['user_id'])


def downgrade():
    op.drop_index('ix_ml_usage_records_user_id', 'ml_usage_records')
    op.drop_column('ml_usage_records', 'user_id')

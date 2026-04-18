"""add billing fields to usage records

Revision ID: l9f0a1b2c3d4
Revises: k8e9f0a1b2c3
Create Date: 2026-04-18 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'l9f0a1b2c3d4'
down_revision = 'k8e9f0a1b2c3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ml_usage_records', sa.Column('payable_amount', sa.Float(), nullable=True, server_default='0'))
    op.add_column('ml_usage_records', sa.Column('discount', sa.Float(), nullable=True, server_default='1'))
    op.add_column('ml_usage_records', sa.Column('actual_amount', sa.Float(), nullable=True, server_default='0'))


def downgrade():
    op.drop_column('ml_usage_records', 'actual_amount')
    op.drop_column('ml_usage_records', 'discount')
    op.drop_column('ml_usage_records', 'payable_amount')

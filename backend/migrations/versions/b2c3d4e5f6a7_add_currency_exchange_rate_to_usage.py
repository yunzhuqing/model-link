"""add_currency_exchange_rate_to_usage_records

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-14 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'ml_usage_records',
        sa.Column('currency', sa.String(length=10), nullable=True, server_default='USD'),
    )
    op.add_column(
        'ml_usage_records',
        sa.Column('exchange_rate_to_cny', sa.Float(), nullable=True),
    )


def downgrade():
    op.drop_column('ml_usage_records', 'exchange_rate_to_cny')
    op.drop_column('ml_usage_records', 'currency')

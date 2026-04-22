"""add exchange_rate and actual_amount_usd, drop exchange_rate_to_cny

Revision ID: o2b3c4d5e6f7
Revises: n1a2b3c4d5e6
Create Date: 2026-04-22 09:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'o2b3c4d5e6f7'
down_revision = 'n1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns
    op.add_column('ml_usage_records', sa.Column('exchange_rate', sa.Float(), nullable=True, server_default='1.0'))
    op.add_column('ml_usage_records', sa.Column('actual_amount_usd', sa.Float(), nullable=True, server_default='0'))

    # Backfill actual_amount_usd from existing data:
    # For USD records (exchange_rate_to_cny was the USD→CNY rate, not 1.0):
    #   actual_amount_usd = actual_amount (already in USD)
    # For CNY records (exchange_rate_to_cny was 1.0):
    #   actual_amount_usd = actual_amount / <current_rate> (but we don't have the rate)
    # Since exchange_rate_to_cny stored: 1.0 for CNY, USD→CNY rate for USD,
    # we can compute: exchange_rate = exchange_rate_to_cny for CNY, 1.0 for USD
    # and actual_amount_usd = actual_amount / exchange_rate
    op.execute("""
        UPDATE ml_usage_records
        SET exchange_rate = CASE
            WHEN UPPER(currency) = 'USD' THEN 1.0
            WHEN exchange_rate_to_cny IS NOT NULL AND exchange_rate_to_cny > 0 THEN exchange_rate_to_cny
            ELSE 7.0
        END,
        actual_amount_usd = CASE
            WHEN UPPER(currency) = 'USD' THEN COALESCE(actual_amount, 0)
            WHEN exchange_rate_to_cny IS NOT NULL AND exchange_rate_to_cny > 0 THEN COALESCE(actual_amount, 0) / exchange_rate_to_cny
            ELSE COALESCE(actual_amount, 0) / 7.0
        END
    """)

    # Drop old column
    op.drop_column('ml_usage_records', 'exchange_rate_to_cny')


def downgrade():
    # Re-add old column
    op.add_column('ml_usage_records', sa.Column('exchange_rate_to_cny', sa.Float(), nullable=True))

    # Backfill exchange_rate_to_cny from exchange_rate
    op.execute("""
        UPDATE ml_usage_records
        SET exchange_rate_to_cny = CASE
            WHEN UPPER(currency) = 'USD' THEN exchange_rate
            ELSE 1.0
        END
    """)

    # Drop new columns
    op.drop_column('ml_usage_records', 'actual_amount_usd')
    op.drop_column('ml_usage_records', 'exchange_rate')

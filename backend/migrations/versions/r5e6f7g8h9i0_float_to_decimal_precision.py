"""float to decimal precision for price/amount/discount fields

Revision ID: r5e6f7g8h9i0
Revises: q4d5e6f7g8h9
Create Date: 2025-04-26 21:50:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'r5e6f7g8h9i0'
down_revision = 'q4d5e6f7g8h9'
branch_labels = None
depends_on = None


def upgrade():
    # ── ml_model_templates ────────────────────────────────────────────────
    with op.batch_alter_table('ml_model_templates', schema=None) as batch_op:
        batch_op.alter_column('input_price', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('output_price', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('cache_creation_price', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('cache_5m_creation_price', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('cache_1h_creation_price', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('cache_hit_price', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('discount', type_=sa.Numeric(10, 4), existing_type=sa.Float())

    # ── ml_models ─────────────────────────────────────────────────────────
    with op.batch_alter_table('ml_models', schema=None) as batch_op:
        batch_op.alter_column('input_price', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('output_price', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('cache_creation_price', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('cache_5m_creation_price', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('cache_1h_creation_price', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('cache_hit_price', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('discount', type_=sa.Numeric(10, 4), existing_type=sa.Float())

    # ── ml_api_key_budgets ────────────────────────────────────────────────
    with op.batch_alter_table('ml_api_key_budgets', schema=None) as batch_op:
        batch_op.alter_column('amount', type_=sa.Numeric(20, 6), existing_type=sa.Float())
        batch_op.alter_column('remaining', type_=sa.Numeric(20, 6), existing_type=sa.Float())

    # ── ml_usage_records ──────────────────────────────────────────────────
    with op.batch_alter_table('ml_usage_records', schema=None) as batch_op:
        batch_op.alter_column('input_price_unit', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('output_price_unit', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('cache_creation_price_unit', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('cache_5m_creation_price_unit', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('cache_1h_creation_price_unit', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('cache_token_price_unit', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('output_image_price_unit', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('output_video_price_unit', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('output_audio_price_unit', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('web_search_price_unit', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('exchange_rate', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('payable_amount', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('discount', type_=sa.Numeric(10, 4), existing_type=sa.Float())
        batch_op.alter_column('actual_amount', type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch_op.alter_column('actual_amount_usd', type_=sa.Numeric(20, 10), existing_type=sa.Float())


def downgrade():
    # ── ml_usage_records ──────────────────────────────────────────────────
    with op.batch_alter_table('ml_usage_records', schema=None) as batch_op:
        batch_op.alter_column('input_price_unit', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('output_price_unit', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('cache_creation_price_unit', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('cache_5m_creation_price_unit', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('cache_1h_creation_price_unit', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('cache_token_price_unit', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('output_image_price_unit', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('output_video_price_unit', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('output_audio_price_unit', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('web_search_price_unit', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('exchange_rate', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('payable_amount', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('discount', type_=sa.Float(), existing_type=sa.Numeric(10, 4))
        batch_op.alter_column('actual_amount', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('actual_amount_usd', type_=sa.Float(), existing_type=sa.Numeric(20, 10))

    # ── ml_api_key_budgets ────────────────────────────────────────────────
    with op.batch_alter_table('ml_api_key_budgets', schema=None) as batch_op:
        batch_op.alter_column('amount', type_=sa.Float(), existing_type=sa.Numeric(20, 6))
        batch_op.alter_column('remaining', type_=sa.Float(), existing_type=sa.Numeric(20, 6))

    # ── ml_models ─────────────────────────────────────────────────────────
    with op.batch_alter_table('ml_models', schema=None) as batch_op:
        batch_op.alter_column('input_price', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('output_price', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('cache_creation_price', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('cache_5m_creation_price', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('cache_1h_creation_price', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('cache_hit_price', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('discount', type_=sa.Float(), existing_type=sa.Numeric(10, 4))

    # ── ml_model_templates ────────────────────────────────────────────────
    with op.batch_alter_table('ml_model_templates', schema=None) as batch_op:
        batch_op.alter_column('input_price', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('output_price', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('cache_creation_price', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('cache_5m_creation_price', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('cache_1h_creation_price', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('cache_hit_price', type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch_op.alter_column('discount', type_=sa.Float(), existing_type=sa.Numeric(10, 4))

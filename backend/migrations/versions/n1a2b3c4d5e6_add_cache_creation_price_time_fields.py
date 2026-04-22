"""add 5m/1h cache creation price fields

Revision ID: n1a2b3c4d5e6
Revises: m0a1b2c3d4e5
Create Date: 2026-04-21 21:36:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'n1a2b3c4d5e6'
down_revision = 'm0a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    # ── ml_model_templates ────────────────────────────────────────────
    op.add_column('ml_model_templates', sa.Column('cache_5m_creation_price', sa.Float(), nullable=True, server_default='0'))
    op.add_column('ml_model_templates', sa.Column('cache_1h_creation_price', sa.Float(), nullable=True, server_default='0'))

    # ── ml_models ─────────────────────────────────────────────────────
    op.add_column('ml_models', sa.Column('cache_5m_creation_price', sa.Float(), nullable=True, server_default='0'))
    op.add_column('ml_models', sa.Column('cache_1h_creation_price', sa.Float(), nullable=True, server_default='0'))

    # ── ml_usage_records ──────────────────────────────────────────────
    op.add_column('ml_usage_records', sa.Column('cache_5m_creation_tokens', sa.BigInteger(), nullable=True, server_default='0'))
    op.add_column('ml_usage_records', sa.Column('cache_5m_creation_price_unit', sa.Float(), nullable=True, server_default='0'))
    op.add_column('ml_usage_records', sa.Column('cache_1h_creation_tokens', sa.BigInteger(), nullable=True, server_default='0'))
    op.add_column('ml_usage_records', sa.Column('cache_1h_creation_price_unit', sa.Float(), nullable=True, server_default='0'))


def downgrade():
    # ── ml_usage_records ──────────────────────────────────────────────
    op.drop_column('ml_usage_records', 'cache_1h_creation_price_unit')
    op.drop_column('ml_usage_records', 'cache_1h_creation_tokens')
    op.drop_column('ml_usage_records', 'cache_5m_creation_price_unit')
    op.drop_column('ml_usage_records', 'cache_5m_creation_tokens')

    # ── ml_models ─────────────────────────────────────────────────────
    op.drop_column('ml_models', 'cache_1h_creation_price')
    op.drop_column('ml_models', 'cache_5m_creation_price')

    # ── ml_model_templates ────────────────────────────────────────────
    op.drop_column('ml_model_templates', 'cache_1h_creation_price')
    op.drop_column('ml_model_templates', 'cache_5m_creation_price')

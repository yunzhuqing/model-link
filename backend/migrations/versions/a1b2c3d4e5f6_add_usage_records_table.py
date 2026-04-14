"""add_usage_records_table

Revision ID: a1b2c3d4e5f6
Revises: c724707f0df2
Create Date: 2026-04-14 11:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'c724707f0df2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ml_usage_records',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        # Identity
        sa.Column('user_name', sa.String(length=100), nullable=True),
        sa.Column('group_id', sa.Integer(), nullable=True),
        sa.Column('group_name', sa.String(length=100), nullable=True),
        sa.Column('api_key_hash', sa.String(length=64), nullable=True),
        sa.Column('api_key_preview', sa.String(length=20), nullable=True),
        sa.Column('api_key_name', sa.String(length=100), nullable=True),
        # Model / Provider
        sa.Column('model_name', sa.String(length=200), nullable=True),
        sa.Column('provider_id', sa.Integer(), nullable=True),
        sa.Column('provider_name', sa.String(length=100), nullable=True),
        # Text tokens
        sa.Column('input_tokens', sa.BigInteger(), nullable=True),
        sa.Column('input_price_unit', sa.Float(), nullable=True),
        sa.Column('output_tokens', sa.BigInteger(), nullable=True),
        sa.Column('output_price_unit', sa.Float(), nullable=True),
        sa.Column('cache_creation_tokens', sa.BigInteger(), nullable=True),
        sa.Column('cache_creation_price_unit', sa.Float(), nullable=True),
        sa.Column('cache_tokens', sa.BigInteger(), nullable=True),
        sa.Column('cache_token_price_unit', sa.Float(), nullable=True),
        sa.Column('reasoning_tokens', sa.BigInteger(), nullable=True),
        # Image output
        sa.Column('output_image_number', sa.Integer(), nullable=True),
        sa.Column('output_image_tokens', sa.BigInteger(), nullable=True),
        sa.Column('output_image_resolution', sa.String(length=50), nullable=True),
        sa.Column('output_image_aspect', sa.String(length=20), nullable=True),
        sa.Column('output_image_price_unit', sa.Float(), nullable=True),
        # Video output
        sa.Column('output_video_number', sa.Integer(), nullable=True),
        sa.Column('output_video_tokens', sa.BigInteger(), nullable=True),
        sa.Column('output_video_resolution', sa.String(length=50), nullable=True),
        sa.Column('output_video_aspect', sa.String(length=20), nullable=True),
        sa.Column('output_video_seconds', sa.Float(), nullable=True),
        sa.Column('output_video_price_unit', sa.Float(), nullable=True),
        # Audio output
        sa.Column('output_audio_tokens', sa.BigInteger(), nullable=True),
        sa.Column('output_audio_seconds', sa.Float(), nullable=True),
        sa.Column('output_audio_price_unit', sa.Float(), nullable=True),
        # Web search
        sa.Column('web_search_requests', sa.Integer(), nullable=True),
        sa.Column('web_search_price_unit', sa.Float(), nullable=True),
        # Timestamp
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    # Indexes for common filter/sort columns
    op.create_index(op.f('ix_ml_usage_records_user_name'), 'ml_usage_records', ['user_name'], unique=False)
    op.create_index(op.f('ix_ml_usage_records_group_id'), 'ml_usage_records', ['group_id'], unique=False)
    op.create_index(op.f('ix_ml_usage_records_group_name'), 'ml_usage_records', ['group_name'], unique=False)
    op.create_index(op.f('ix_ml_usage_records_api_key_hash'), 'ml_usage_records', ['api_key_hash'], unique=False)
    op.create_index(op.f('ix_ml_usage_records_model_name'), 'ml_usage_records', ['model_name'], unique=False)
    op.create_index(op.f('ix_ml_usage_records_provider_id'), 'ml_usage_records', ['provider_id'], unique=False)
    op.create_index(op.f('ix_ml_usage_records_provider_name'), 'ml_usage_records', ['provider_name'], unique=False)
    op.create_index(op.f('ix_ml_usage_records_created_at'), 'ml_usage_records', ['created_at'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_ml_usage_records_created_at'), table_name='ml_usage_records')
    op.drop_index(op.f('ix_ml_usage_records_provider_name'), table_name='ml_usage_records')
    op.drop_index(op.f('ix_ml_usage_records_provider_id'), table_name='ml_usage_records')
    op.drop_index(op.f('ix_ml_usage_records_model_name'), table_name='ml_usage_records')
    op.drop_index(op.f('ix_ml_usage_records_api_key_hash'), table_name='ml_usage_records')
    op.drop_index(op.f('ix_ml_usage_records_group_name'), table_name='ml_usage_records')
    op.drop_index(op.f('ix_ml_usage_records_group_id'), table_name='ml_usage_records')
    op.drop_index(op.f('ix_ml_usage_records_user_name'), table_name='ml_usage_records')
    op.drop_table('ml_usage_records')

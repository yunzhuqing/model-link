"""add ml_model_templates table

Revision ID: i5j6k7l8m9n0
Revises: h4i5j6k7l8m9
Create Date: 2026-03-28 17:27:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'i5j6k7l8m9n0'
down_revision = 'h4i5j6k7l8m9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ml_model_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(100), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('alias', sa.String(100), nullable=True),
        sa.Column('context_size', sa.Integer(), nullable=True, server_default='4096'),
        sa.Column('input_size', sa.Integer(), nullable=True, server_default='4096'),
        sa.Column('input_price', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('output_price', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('cache_creation_price', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('cache_hit_price', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('support_kvcache', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('support_image', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('support_audio', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('support_video', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('support_file', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('support_web_search', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('support_tool_search', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('support_thinking', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('support_online_image', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('support_online_video', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('support_embedding', sa.Boolean(), nullable=True, server_default='0'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ml_model_templates_id'), 'ml_model_templates', ['id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_ml_model_templates_id'), table_name='ml_model_templates')
    op.drop_table('ml_model_templates')

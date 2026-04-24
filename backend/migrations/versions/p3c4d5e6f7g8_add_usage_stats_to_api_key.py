"""add usage stats fields to api_key

Revision ID: p3c4d5e6f7g8
Revises: o2b3c4d5e6f7
Create Date: 2026-04-23 16:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'p3c4d5e6f7g8'
down_revision = 'o2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ml_api_keys', schema=None) as batch_op:
        batch_op.add_column(sa.Column('total_input_tokens', sa.BigInteger(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('total_output_tokens', sa.BigInteger(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('total_reasoning_tokens', sa.BigInteger(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('total_cost_usd', sa.Float(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('total_image_count', sa.Integer(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('total_video_count', sa.Integer(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('total_audio_seconds', sa.Float(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('unlimited_budget', sa.Boolean(), nullable=False, server_default='1'))


def downgrade():
    with op.batch_alter_table('ml_api_keys', schema=None) as batch_op:
        batch_op.drop_column('unlimited_budget')
        batch_op.drop_column('total_audio_seconds')
        batch_op.drop_column('total_video_count')
        batch_op.drop_column('total_image_count')
        batch_op.drop_column('total_cost_usd')
        batch_op.drop_column('total_reasoning_tokens')
        batch_op.drop_column('total_output_tokens')
        batch_op.drop_column('total_input_tokens')

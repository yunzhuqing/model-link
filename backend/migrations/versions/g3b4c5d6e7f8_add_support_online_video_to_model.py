"""add support_online_video to model

Revision ID: g3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-03-24 18:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'g3b4c5d6e7f8'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ml_models', schema=None) as batch_op:
        batch_op.add_column(sa.Column('support_online_video', sa.Boolean(), nullable=True, server_default=sa.text('1')))


def downgrade():
    with op.batch_alter_table('ml_models', schema=None) as batch_op:
        batch_op.drop_column('support_online_video')

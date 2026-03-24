"""add support_online_image to model

Revision ID: f2a3b4c5d6e7
Revises: e1ceb4665f19
Create Date: 2026-03-24 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2a3b4c5d6e7'
down_revision = 'e1ceb4665f19'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ml_models', schema=None) as batch_op:
        batch_op.add_column(sa.Column('support_online_image', sa.Boolean(), nullable=True, server_default=sa.text('1')))


def downgrade():
    with op.batch_alter_table('ml_models', schema=None) as batch_op:
        batch_op.drop_column('support_online_image')

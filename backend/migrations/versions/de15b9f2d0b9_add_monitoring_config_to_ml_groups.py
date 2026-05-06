"""add monitoring_config to ml_groups

Revision ID: de15b9f2d0b9
Revises: y4d5e6f7g8h9
Create Date: 2026-05-05 21:32:26.096624

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'de15b9f2d0b9'
down_revision = 'y4d5e6f7g8h9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ml_groups', schema=None) as batch_op:
        batch_op.add_column(sa.Column('monitoring_config', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('ml_groups', schema=None) as batch_op:
        batch_op.drop_column('monitoring_config')

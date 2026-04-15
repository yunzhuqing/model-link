"""add budget to api_key

Revision ID: h5b6c7d8e9f0
Revises: g4a5b6c7d8e9
Create Date: 2025-04-15 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'h5b6c7d8e9f0'
down_revision = 'g4a5b6c7d8e9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ml_api_keys', schema=None) as batch_op:
        batch_op.add_column(sa.Column('budget', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('ml_api_keys', schema=None) as batch_op:
        batch_op.drop_column('budget')

"""add description column to ml_api_keys

Revision ID: y4d5e6f7g8h9
Revises: 2c9f01a961c9
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'y4d5e6f7g8h9'
down_revision = '2c9f01a961c9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ml_api_keys', schema=None) as batch_op:
        batch_op.add_column(sa.Column('description', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('ml_api_keys', schema=None) as batch_op:
        batch_op.drop_column('description')

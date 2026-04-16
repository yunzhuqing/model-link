"""add duration_ms to usage records

Revision ID: i6c7d8e9f0a1
Revises: h5b6c7d8e9f0
Create Date: 2026-04-15 14:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'i6c7d8e9f0a1'
down_revision = 'h5b6c7d8e9f0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ml_usage_records', sa.Column('duration_ms', sa.BigInteger(), nullable=True))


def downgrade():
    op.drop_column('ml_usage_records', 'duration_ms')

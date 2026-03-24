"""add support_embedding field to model

Revision ID: h4i5j6k7l8m9
Revises: g3b4c5d6e7f8
Create Date: 2026-03-24 20:14:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'h4i5j6k7l8m9'
down_revision = 'g3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade():
    # Add support_embedding column to ml_models table
    op.add_column('ml_models', sa.Column('support_embedding', sa.Boolean(), nullable=True, server_default='0'))
    op.execute("UPDATE ml_models SET support_embedding = 0 WHERE support_embedding IS NULL")


def downgrade():
    # Remove support_embedding column from ml_models table
    op.drop_column('ml_models', 'support_embedding')
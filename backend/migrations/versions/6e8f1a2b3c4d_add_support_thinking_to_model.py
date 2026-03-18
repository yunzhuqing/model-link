"""add support_thinking to model

Revision ID: 6e8f1a2b3c4d
Revises: 2307e81a21fb
Create Date: 2026-03-18 21:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6e8f1a2b3c4d'
down_revision = '2307e81a21fb'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ml_models', schema=None) as batch_op:
        batch_op.add_column(sa.Column('support_thinking', sa.Boolean(), nullable=True))

    # Set default value for existing rows
    op.execute("UPDATE ml_models SET support_thinking = false WHERE support_thinking IS NULL")


def downgrade():
    with op.batch_alter_table('ml_models', schema=None) as batch_op:
        batch_op.drop_column('support_thinking')

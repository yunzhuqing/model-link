"""add api_key_budgets table

Revision ID: q4d5e6f7g8h9
Revises: p3c4d5e6f7g8
Create Date: 2025-04-26 20:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'q4d5e6f7g8h9'
down_revision = 'p3c4d5e6f7g8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ml_api_key_budgets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('api_key_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(20, 6), nullable=False, server_default='0'),
        sa.Column('remaining', sa.Numeric(20, 6), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['api_key_id'], ['ml_api_keys.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ml_api_key_budgets_api_key_id', 'ml_api_key_budgets', ['api_key_id'])


def downgrade():
    op.drop_index('ix_ml_api_key_budgets_api_key_id', table_name='ml_api_key_budgets')
    op.drop_table('ml_api_key_budgets')

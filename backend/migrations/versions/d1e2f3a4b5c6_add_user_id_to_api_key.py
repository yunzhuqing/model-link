"""add user_id to api_key

Revision ID: d1e2f3a4b5c6
Revises: b2c3d4e5f6a7
Create Date: 2026-04-14 17:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd1e2f3a4b5c6'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ml_api_keys', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_ml_api_keys_user_id'), 'ml_api_keys', ['user_id'], unique=False)
    op.create_foreign_key('fk_api_keys_user_id', 'ml_api_keys', 'ml_users', ['user_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_api_keys_user_id', 'ml_api_keys', type_='foreignkey')
    op.drop_index(op.f('ix_ml_api_keys_user_id'), table_name='ml_api_keys')
    op.drop_column('ml_api_keys', 'user_id')

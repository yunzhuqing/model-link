"""add ml_permissions table for per-group permission management

Revision ID: w2b3c4d5e6f7
Revises: v1a2b3c4d5e6
Create Date: 2025-05-03
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'w2b3c4d5e6f7'
down_revision = 'v1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ml_permissions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('label', sa.String(length=200), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('allowed_roles', sa.JSON(), nullable=False, server_default=sa.text("'[\"root\"]'")),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['group_id'], ['ml_groups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('group_id', 'key', name='uq_permission_group_key'),
    )
    op.create_index(op.f('ix_ml_permissions_group_id'), 'ml_permissions', ['group_id'])
    op.create_index(op.f('ix_ml_permissions_key'), 'ml_permissions', ['key'])


def downgrade():
    op.drop_index(op.f('ix_ml_permissions_key'), table_name='ml_permissions')
    op.drop_index(op.f('ix_ml_permissions_group_id'), table_name='ml_permissions')
    op.drop_table('ml_permissions')
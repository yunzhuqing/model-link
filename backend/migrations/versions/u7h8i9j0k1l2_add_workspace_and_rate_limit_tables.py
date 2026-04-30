"""Add workspace and workspace_rate_limits tables, workspace_id to users and api_keys.

Revision ID: u7h8i9j0k1l2
Revises: t6g7h8i9j0k1
Create Date: 2026-04-29 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'u7h8i9j0k1l2'
down_revision = 't6g7h8i9j0k1'
branch_labels = None
depends_on = None


def upgrade():
    # Create ml_workspaces table (skip if already exists)
    if not op.get_bind().dialect.has_table(op.get_bind(), 'ml_workspaces'):
        op.create_table(
            'ml_workspaces',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('name', sa.String(100), nullable=False, unique=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_ml_workspaces_id', 'ml_workspaces', ['id'])
        op.create_index('ix_ml_workspaces_name', 'ml_workspaces', ['name'])

    # Create ml_workspace_rate_limits table (skip if already exists)
    if not op.get_bind().dialect.has_table(op.get_bind(), 'ml_workspace_rate_limits'):
        op.create_table(
            'ml_workspace_rate_limits',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('ml_workspaces.id', ondelete='CASCADE'), nullable=False),
            sa.Column('model_name', sa.String(100), nullable=False),
            sa.Column('rpm', sa.Integer(), nullable=True),
            sa.Column('tpm', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('workspace_id', 'model_name', name='uq_workspace_model_rate_limit'),
        )
        op.create_index('ix_ml_workspace_rate_limits_id', 'ml_workspace_rate_limits', ['id'])
        op.create_index('ix_ml_workspace_rate_limits_workspace_id', 'ml_workspace_rate_limits', ['workspace_id'])
        op.create_index('ix_ml_workspace_rate_limits_model_name', 'ml_workspace_rate_limits', ['model_name'])

    # Add workspace_id to ml_groups
    op.add_column('ml_groups', sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('ml_workspaces.id'), nullable=True))
    op.create_index('ix_ml_groups_workspace_id', 'ml_groups', ['workspace_id'])

    # Add workspace_id to ml_api_keys
    op.add_column('ml_api_keys', sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('ml_workspaces.id'), nullable=True))
    op.create_index('ix_ml_api_keys_workspace_id', 'ml_api_keys', ['workspace_id'])


def downgrade():
    # Drop workspace_id from ml_api_keys
    op.drop_index('ix_ml_api_keys_workspace_id', table_name='ml_api_keys')
    op.drop_column('ml_api_keys', 'workspace_id')

    # Drop workspace_id from ml_groups
    op.drop_index('ix_ml_groups_workspace_id', table_name='ml_groups')
    op.drop_column('ml_groups', 'workspace_id')

    # Drop ml_workspace_rate_limits
    op.drop_index('ix_ml_workspace_rate_limits_model_name', table_name='ml_workspace_rate_limits')
    op.drop_index('ix_ml_workspace_rate_limits_workspace_id', table_name='ml_workspace_rate_limits')
    op.drop_index('ix_ml_workspace_rate_limits_id', table_name='ml_workspace_rate_limits')
    op.drop_table('ml_workspace_rate_limits')

    # Drop ml_workspaces
    op.drop_index('ix_ml_workspaces_name', table_name='ml_workspaces')
    op.drop_index('ix_ml_workspaces_id', table_name='ml_workspaces')
    op.drop_table('ml_workspaces')
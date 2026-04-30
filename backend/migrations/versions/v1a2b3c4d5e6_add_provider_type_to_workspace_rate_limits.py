"""Add provider_type and provider_id to workspace_rate_limits

Revision ID: v1a2b3c4d5e6
Revises: u7h8i9j0k1l2
Create Date: 2026-04-30

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'v1a2b3c4d5e6'
down_revision = 'u7h8i9j0k1l2'
branch_labels = None
depends_on = None


def upgrade():
    # Add provider_type column (NOT NULL with default for existing rows)
    op.add_column('ml_workspace_rate_limits',
                  sa.Column('provider_type', sa.String(50), nullable=True, index=True))

    # Set default value for existing rows
    op.execute("UPDATE ml_workspace_rate_limits SET provider_type = 'openai' WHERE provider_type IS NULL")

    # Make provider_type NOT NULL
    op.alter_column('ml_workspace_rate_limits', 'provider_type',
                    existing_type=sa.String(50), nullable=False)

    # Add provider_id column (nullable — NULL means shared for all accounts of this type)
    op.add_column('ml_workspace_rate_limits',
                  sa.Column('provider_id', sa.Integer(),
                            sa.ForeignKey('ml_providers.id', ondelete='CASCADE'),
                            nullable=True, index=True))

    # Drop old unique constraint
    op.drop_constraint('uq_workspace_model_rate_limit', 'ml_workspace_rate_limits', type_='unique')

    # Add new unique constraint including provider_type and provider_id
    op.create_unique_constraint(
        'uq_workspace_model_provider_rate_limit',
        'ml_workspace_rate_limits',
        ['workspace_id', 'model_name', 'provider_type', 'provider_id']
    )


def downgrade():
    # Drop new unique constraint
    op.drop_constraint('uq_workspace_model_provider_rate_limit', 'ml_workspace_rate_limits', type_='unique')

    # Restore old unique constraint
    op.create_unique_constraint(
        'uq_workspace_model_rate_limit',
        'ml_workspace_rate_limits',
        ['workspace_id', 'model_name']
    )

    # Drop columns
    op.drop_column('ml_workspace_rate_limits', 'provider_id')
    op.drop_column('ml_workspace_rate_limits', 'provider_type')

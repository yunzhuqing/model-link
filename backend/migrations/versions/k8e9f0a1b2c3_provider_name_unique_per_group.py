"""provider name unique per group instead of globally

Revision ID: k8e9f0a1b2c3
Revises: j7d8e9f0a1b2
Create Date: 2026-04-17 09:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'k8e9f0a1b2c3'
down_revision = 'j7d8e9f0a1b2'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the old global unique index on provider name
    op.drop_index('ix_ml_providers_name', table_name='ml_providers')

    # Re-create a non-unique index on name (for query performance)
    op.create_index('ix_ml_providers_name', 'ml_providers', ['name'], unique=False)

    # Add composite unique constraint: name must be unique within the same group
    op.create_unique_constraint('uq_provider_name_group', 'ml_providers', ['name', 'group_id'])


def downgrade():
    # Remove composite unique constraint
    op.drop_constraint('uq_provider_name_group', 'ml_providers', type_='unique')

    # Drop the non-unique index
    op.drop_index('ix_ml_providers_name', table_name='ml_providers')

    # Restore the global unique index on name
    op.create_index('ix_ml_providers_name', 'ml_providers', ['name'], unique=True)

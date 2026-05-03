"""remove group_id from ml_permissions to make permissions system-global

Revision ID: x3c4d5e6f7g8
Revises: w2b3c4d5e6f7
Create Date: 2025-05-03
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'x3c4d5e6f7g8'
down_revision = 'w2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the unique constraint that includes group_id
    op.drop_constraint('uq_permission_group_key', 'ml_permissions', type_='unique')
    # Drop the foreign key constraint
    op.drop_constraint(None, 'ml_permissions', type_='foreignkey')  # SQLAlchemy auto-named it
    # Drop the group_id column
    op.drop_column('ml_permissions', 'group_id')
    # Re-add unique constraint on key alone
    op.create_unique_constraint('uq_permission_key', 'ml_permissions', ['key'])


def downgrade():
    op.drop_constraint('uq_permission_key', 'ml_permissions', type_='unique')
    op.add_column('ml_permissions', sa.Column('group_id', sa.Integer(), nullable=True))
    # We cannot restore meaningful group_id values, so leave nullable
    op.create_unique_constraint('uq_permission_group_key', 'ml_permissions', ['group_id', 'key'])
    op.create_foreign_key(None, 'ml_permissions', 'ml_groups', ['group_id'], ['id'], ondelete='CASCADE')
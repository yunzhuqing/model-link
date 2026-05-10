"""drop group_id from ml_permissions

Revision ID: x3c4d5e6f7g8
Revises: 2e80243d5136
Create Date: 2026-05-10
"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 'x3c4d5e6f7g8'
down_revision = '2e80243d5136'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ml_permissions', schema=None) as batch_op:
        batch_op.drop_constraint('ml_permissions_ibfk_1', type_='foreignkey')
        batch_op.drop_column('group_id')


def downgrade():
    with op.batch_alter_table('ml_permissions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('group_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'ml_permissions_ibfk_1', 'ml_groups', ['group_id'], ['id'], ondelete='CASCADE'
        )
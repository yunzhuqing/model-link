"""add uploaded_files table

Revision ID: b46eff060f66
Revises: 3a00efa7e8da
Create Date: 2026-06-18 20:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b46eff060f66'
down_revision = '3a00efa7e8da'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ml_uploaded_files',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('file_id', sa.String(length=200), nullable=False),
    sa.Column('object_key', sa.String(length=500), nullable=False),
    sa.Column('purpose', sa.String(length=100), nullable=True),
    sa.Column('group_id', sa.Integer(), nullable=True),
    sa.Column('api_key', sa.String(length=100), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('client_user_id', sa.String(length=100), nullable=True),
    sa.Column('type', sa.String(length=50), nullable=False, server_default='volcengine'),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('ml_uploaded_files', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ml_uploaded_files_file_id'), ['file_id'], unique=True)
        batch_op.create_index(batch_op.f('ix_ml_uploaded_files_group_id'), ['group_id'], unique=False)


def downgrade():
    with op.batch_alter_table('ml_uploaded_files', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ml_uploaded_files_group_id'))
        batch_op.drop_index(batch_op.f('ix_ml_uploaded_files_file_id'))

    op.drop_table('ml_uploaded_files')

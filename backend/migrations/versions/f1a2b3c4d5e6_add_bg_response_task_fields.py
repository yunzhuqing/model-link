"""add bg_response task fields

Revision ID: f1a2b3c4d5e6
Revises: e07ca08127e1
Create Date: 2026-05-19 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f1a2b3c4d5e6'
down_revision = 'e07ca08127e1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ml_background_responses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('task_id', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('provider_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('session_id', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('request_id', sa.String(length=64), nullable=True))
        batch_op.create_index('ix_ml_background_responses_status_created', ['status', 'created_at'], unique=False)
        batch_op.create_index('ix_ml_background_responses_task_id', ['task_id'], unique=False)


def downgrade():
    with op.batch_alter_table('ml_background_responses', schema=None) as batch_op:
        batch_op.drop_index('ix_ml_background_responses_task_id')
        batch_op.drop_index('ix_ml_background_responses_status_created')
        batch_op.drop_column('request_id')
        batch_op.drop_column('session_id')
        batch_op.drop_column('provider_id')
        batch_op.drop_column('task_id')
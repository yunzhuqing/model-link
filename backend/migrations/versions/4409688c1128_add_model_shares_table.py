"""add model shares table

Revision ID: 4409688c1128
Revises: x3c4d5e6f7g8
Create Date: 2026-05-10 19:09:52.517194

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '4409688c1128'
down_revision = 'x3c4d5e6f7g8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ml_model_shares',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('model_id', sa.Integer(), nullable=False),
    sa.Column('source_group_id', sa.Integer(), nullable=False),
    sa.Column('target_group_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['ml_users.id'], ),
    sa.ForeignKeyConstraint(['model_id'], ['ml_models.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_group_id'], ['ml_groups.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_group_id'], ['ml_groups.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('model_id', 'target_group_id', name='uq_model_share_target')
    )


def downgrade():
    op.drop_table('ml_model_shares')

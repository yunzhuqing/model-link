"""add api_type to models

Revision ID: c1d2e3f4a5b6
Revises: b46eff060f66
Create Date: 2026-06-19 06:48:12.304284

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1d2e3f4a5b6'
down_revision = 'b46eff060f66'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ml_models', schema=None) as batch_op:
        batch_op.add_column(sa.Column('api_type', sa.String(length=100), nullable=True))

    with op.batch_alter_table('ml_model_templates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('api_type', sa.String(length=100), nullable=True))


def downgrade():
    with op.batch_alter_table('ml_models', schema=None) as batch_op:
        batch_op.drop_column('api_type')

    with op.batch_alter_table('ml_model_templates', schema=None) as batch_op:
        batch_op.drop_column('api_type')

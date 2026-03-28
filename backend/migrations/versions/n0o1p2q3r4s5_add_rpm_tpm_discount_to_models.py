"""add rpm, tpm, discount to ml_models and ml_model_templates

Revision ID: n0o1p2q3r4s5
Revises: m9n0o1p2q3r4
Create Date: 2026-03-28

"""
from alembic import op
import sqlalchemy as sa

revision = 'n0o1p2q3r4s5'
down_revision = 'm9n0o1p2q3r4'
branch_labels = None
depends_on = None


def upgrade():
    # ml_model_templates
    op.add_column('ml_model_templates',
        sa.Column('rpm', sa.Integer(), nullable=True)
    )
    op.add_column('ml_model_templates',
        sa.Column('tpm', sa.Integer(), nullable=True)
    )
    op.add_column('ml_model_templates',
        sa.Column('discount', sa.Float(), nullable=True)
    )

    # ml_models
    op.add_column('ml_models',
        sa.Column('rpm', sa.Integer(), nullable=True)
    )
    op.add_column('ml_models',
        sa.Column('tpm', sa.Integer(), nullable=True)
    )
    op.add_column('ml_models',
        sa.Column('discount', sa.Float(), nullable=True)
    )

    # Set default discount = 1.0 for existing rows
    op.execute('UPDATE ml_model_templates SET discount = 1.0 WHERE discount IS NULL')
    op.execute('UPDATE ml_models SET discount = 1.0 WHERE discount IS NULL')


def downgrade():
    op.drop_column('ml_model_templates', 'discount')
    op.drop_column('ml_model_templates', 'tpm')
    op.drop_column('ml_model_templates', 'rpm')
    op.drop_column('ml_models', 'discount')
    op.drop_column('ml_models', 'tpm')
    op.drop_column('ml_models', 'rpm')

"""add currency and retirement_time to ml_models and ml_model_templates

Revision ID: m9n0o1p2q3r4
Revises: l8m9n0o1p2q3
Create Date: 2026-03-28

"""
from alembic import op
import sqlalchemy as sa

revision = 'm9n0o1p2q3r4'
down_revision = 'l8m9n0o1p2q3'
branch_labels = None
depends_on = None


def upgrade():
    # Add currency and retirement_time to ml_model_templates
    op.add_column('ml_model_templates',
        sa.Column('currency', sa.String(length=10), nullable=True)
    )
    op.add_column('ml_model_templates',
        sa.Column('retirement_time', sa.DateTime(), nullable=True)
    )

    # Add currency and retirement_time to ml_models
    op.add_column('ml_models',
        sa.Column('currency', sa.String(length=10), nullable=True)
    )
    op.add_column('ml_models',
        sa.Column('retirement_time', sa.DateTime(), nullable=True)
    )

    # Set default value 'USD' for existing rows
    op.execute("UPDATE ml_model_templates SET currency = 'USD' WHERE currency IS NULL")
    op.execute("UPDATE ml_models SET currency = 'USD' WHERE currency IS NULL")


def downgrade():
    op.drop_column('ml_model_templates', 'retirement_time')
    op.drop_column('ml_model_templates', 'currency')
    op.drop_column('ml_models', 'retirement_time')
    op.drop_column('ml_models', 'currency')

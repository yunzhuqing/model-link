"""add output_size, reasoning_effort, supported_image_formats to ml_models and ml_model_templates

Revision ID: j6k7l8m9n0o1
Revises: i5j6k7l8m9n0
Create Date: 2026-03-28 17:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'j6k7l8m9n0o1'
down_revision = 'i5j6k7l8m9n0'
branch_labels = None
depends_on = None


def upgrade():
    # ── ml_models ────────────────────────────────────────────────────────────
    op.add_column('ml_models', sa.Column('output_size', sa.Integer(), nullable=True, server_default='4096'))
    op.add_column('ml_models', sa.Column('reasoning_effort', sa.String(20), nullable=True))
    op.add_column('ml_models', sa.Column('supported_image_formats', sa.String(255), nullable=True))

    # ── ml_model_templates ───────────────────────────────────────────────────
    op.add_column('ml_model_templates', sa.Column('output_size', sa.Integer(), nullable=True, server_default='4096'))
    op.add_column('ml_model_templates', sa.Column('reasoning_effort', sa.String(20), nullable=True))
    op.add_column('ml_model_templates', sa.Column('supported_image_formats', sa.String(255), nullable=True))


def downgrade():
    op.drop_column('ml_models', 'output_size')
    op.drop_column('ml_models', 'reasoning_effort')
    op.drop_column('ml_models', 'supported_image_formats')

    op.drop_column('ml_model_templates', 'output_size')
    op.drop_column('ml_model_templates', 'reasoning_effort')
    op.drop_column('ml_model_templates', 'supported_image_formats')

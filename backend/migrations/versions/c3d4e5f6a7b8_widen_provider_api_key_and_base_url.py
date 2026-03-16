"""Widen provider api_key to Text and base_url to varchar(500)

Revision ID: c3d4e5f6a7b8
Revises: b1c6090babb8
Create Date: 2026-03-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = '2307e81a21fb'
branch_labels = None
depends_on = None


def upgrade():
    # Change api_key from varchar(255) to TEXT (unlimited)
    op.alter_column('ml_providers', 'api_key',
                    existing_type=sa.String(255),
                    type_=sa.Text(),
                    existing_nullable=True)
    
    # Change base_url from varchar(255) to varchar(500)
    op.alter_column('ml_providers', 'base_url',
                    existing_type=sa.String(255),
                    type_=sa.String(500),
                    existing_nullable=True)


def downgrade():
    op.alter_column('ml_providers', 'api_key',
                    existing_type=sa.Text(),
                    type_=sa.String(255),
                    existing_nullable=True)
    
    op.alter_column('ml_providers', 'base_url',
                    existing_type=sa.String(500),
                    type_=sa.String(255),
                    existing_nullable=True)

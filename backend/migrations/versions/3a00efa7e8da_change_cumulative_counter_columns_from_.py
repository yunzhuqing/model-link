"""change cumulative counter columns from Integer to BigInteger

Revision ID: 3a00efa7e8da
Revises: 08a0358306d4
Create Date: 2026-06-03 19:54:04.441718

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3a00efa7e8da'
down_revision = '08a0358306d4'
branch_labels = None
depends_on = None


def upgrade():
    # Widen cumulative counter columns from INT to BIGINT to prevent overflow.
    # These columns accumulate forever; INT (max 2.1B) has already overflowed
    # for token_count in production.
    op.alter_column('ml_api_keys', 'request_count',
                    existing_type=sa.Integer(),
                    type_=sa.BigInteger(),
                    existing_nullable=True)
    op.alter_column('ml_api_keys', 'token_count',
                    existing_type=sa.Integer(),
                    type_=sa.BigInteger(),
                    existing_nullable=True)
    op.alter_column('ml_api_keys', 'total_image_count',
                    existing_type=sa.Integer(),
                    type_=sa.BigInteger(),
                    existing_nullable=True)
    op.alter_column('ml_api_keys', 'total_video_count',
                    existing_type=sa.Integer(),
                    type_=sa.BigInteger(),
                    existing_nullable=True)
    op.alter_column('ml_api_keys', 'total_web_search_requests',
                    existing_type=sa.Integer(),
                    type_=sa.BigInteger(),
                    existing_nullable=True)


def downgrade():
    # Narrow back to INT — WARNING: will fail if values exceed INT max.
    op.alter_column('ml_api_keys', 'request_count',
                    existing_type=sa.BigInteger(),
                    type_=sa.Integer(),
                    existing_nullable=True)
    op.alter_column('ml_api_keys', 'token_count',
                    existing_type=sa.BigInteger(),
                    type_=sa.Integer(),
                    existing_nullable=True)
    op.alter_column('ml_api_keys', 'total_image_count',
                    existing_type=sa.BigInteger(),
                    type_=sa.Integer(),
                    existing_nullable=True)
    op.alter_column('ml_api_keys', 'total_video_count',
                    existing_type=sa.BigInteger(),
                    type_=sa.Integer(),
                    existing_nullable=True)
    op.alter_column('ml_api_keys', 'total_web_search_requests',
                    existing_type=sa.BigInteger(),
                    type_=sa.Integer(),
                    existing_nullable=True)

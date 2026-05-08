"""add tags

Revision ID: z5e6f7g8h9i0
Revises: y4d5e6f7g8h9
Create Date: 2026-05-08
"""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = 'z5e6f7g8h9i0'
down_revision = 'y4d5e6f7g8h9'
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    conn = op.get_bind()
    insp = inspect(conn)
    return table_name in insp.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    insp = inspect(conn)
    return column_name in [c["name"] for c in insp.get_columns(table_name)]


def upgrade():
    if not _has_table("ml_tags"):
        op.create_table(
            'ml_tags',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('value', sa.String(200), nullable=False),
            sa.Column('description', sa.String(500), nullable=True, server_default=''),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name', 'value', name='uq_tag_name_value'),
        )
        op.create_index(op.f('ix_ml_tags_name'), 'ml_tags', ['name'], unique=False)

    if not _has_column("ml_groups", "tags"):
        op.add_column('ml_groups', sa.Column('tags', sa.JSON(), nullable=True))

    if not _has_column("ml_api_keys", "tags"):
        op.add_column('ml_api_keys', sa.Column('tags', sa.JSON(), nullable=True))


def downgrade():
    if _has_column("ml_api_keys", "tags"):
        op.drop_column('ml_api_keys', 'tags')
    if _has_column("ml_groups", "tags"):
        op.drop_column('ml_groups', 'tags')
    if _has_table("ml_tags"):
        op.drop_index(op.f('ix_ml_tags_name'), table_name='ml_tags')
        op.drop_table('ml_tags')

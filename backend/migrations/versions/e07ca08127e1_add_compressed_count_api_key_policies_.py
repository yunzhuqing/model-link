"""add compressed_count, api_key_policies, last_compress_id

Revision ID: e07ca08127e1
Revises: c06b5f30e164
Create Date: 2026-05-17 09:02:49.767093

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e07ca08127e1'
down_revision = 'c06b5f30e164'
branch_labels = None
depends_on = None


def upgrade():
    from alembic import context
    conn = context.get_context().connection
    inspector = sa.inspect(conn)

    # ── ml_api_key_policies table (skip if already exists) ──
    tables = inspector.get_table_names()
    if 'ml_api_key_policies' not in tables:
        op.create_table('ml_api_key_policies',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('api_key_id', sa.Integer(), nullable=False),
        sa.Column('policy_type', sa.String(length=50), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['api_key_id'], ['ml_api_keys.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('api_key_id', 'policy_type', name='uq_api_key_policy_type')
        )
        with op.batch_alter_table('ml_api_key_policies', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_ml_api_key_policies_api_key_id'), ['api_key_id'], unique=False)

    # ── ml_api_keys.last_compress_id (skip if already exists) ──
    api_keys_cols = [c['name'] for c in inspector.get_columns('ml_api_keys')]
    if 'last_compress_id' not in api_keys_cols:
        with op.batch_alter_table('ml_api_keys', schema=None) as batch_op:
            batch_op.add_column(sa.Column('last_compress_id', sa.BigInteger(), nullable=False, server_default='0'))

    # ── ml_usage_records.compressed_count (skip if already exists) ──
    usage_cols = [c['name'] for c in inspector.get_columns('ml_usage_records')]
    if 'compressed_count' not in usage_cols:
        with op.batch_alter_table('ml_usage_records', schema=None) as batch_op:
            batch_op.add_column(sa.Column('compressed_count', sa.Integer(), nullable=True, server_default='1'))


def downgrade():
    from alembic import context
    conn = context.get_context().connection
    inspector = sa.inspect(conn)

    tables = inspector.get_table_names()

    # ── Drop compressed_count ──
    if 'ml_usage_records' in tables:
        usage_cols = [c['name'] for c in inspector.get_columns('ml_usage_records')]
        if 'compressed_count' in usage_cols:
            with op.batch_alter_table('ml_usage_records', schema=None) as batch_op:
                batch_op.drop_column('compressed_count')

    # ── Drop last_compress_id ──
    if 'ml_api_keys' in tables:
        api_keys_cols = [c['name'] for c in inspector.get_columns('ml_api_keys')]
        if 'last_compress_id' in api_keys_cols:
            with op.batch_alter_table('ml_api_keys', schema=None) as batch_op:
                batch_op.drop_column('last_compress_id')

    # ── Drop ml_api_key_policies ──
    if 'ml_api_key_policies' in tables:
        with op.batch_alter_table('ml_api_key_policies', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_ml_api_key_policies_api_key_id'))
        op.drop_table('ml_api_key_policies')

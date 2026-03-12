"""add role to user_groups

Revision ID: 5a7b8c9d0e1f
Revises: 4b9c6d8e0f13
Create Date: 2026-03-12 16:14:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5a7b8c9d0e1f'
down_revision = '4b9c6d8e0f13'
branch_labels = None
depends_on = None


def upgrade():
    # Check if role column already exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('ml_user_groups')]
    
    if 'role' not in columns:
        op.add_column('ml_user_groups', sa.Column('role', sa.String(20), nullable=True))
        # Set default role for existing records
        op.execute("UPDATE ml_user_groups SET role = 'root' WHERE role IS NULL")
        # Make column non-nullable after setting defaults (MySQL requires existing type)
        op.alter_column('ml_user_groups', 'role', 
                        existing_type=sa.String(20), 
                        nullable=False)


def downgrade():
    op.drop_column('ml_user_groups', 'role')
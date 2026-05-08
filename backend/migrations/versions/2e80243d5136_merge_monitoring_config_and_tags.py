"""merge monitoring_config and tags

Revision ID: 2e80243d5136
Revises: de15b9f2d0b9, z5e6f7g8h9i0
Create Date: 2026-05-08 15:18:22.835716

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2e80243d5136'
down_revision = ('de15b9f2d0b9', 'z5e6f7g8h9i0')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass

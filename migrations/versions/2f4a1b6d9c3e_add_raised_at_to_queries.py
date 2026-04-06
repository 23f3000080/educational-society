"""Add raised_at to queries

Revision ID: 2f4a1b6d9c3e
Revises: 7d2f3e8c91aa
Create Date: 2026-04-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2f4a1b6d9c3e'
down_revision = '7d2f3e8c91aa'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('queries')}

    if 'raised_at' not in columns:
        with op.batch_alter_table('queries', schema=None) as batch_op:
            batch_op.add_column(sa.Column('raised_at', sa.DateTime(timezone=True), nullable=True))

    op.execute("UPDATE queries SET raised_at = created_at WHERE raised_at IS NULL")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('queries')}

    if 'raised_at' in columns:
        with op.batch_alter_table('queries', schema=None) as batch_op:
            batch_op.drop_column('raised_at')

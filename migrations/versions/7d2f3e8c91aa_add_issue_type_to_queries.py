"""Add issue type to queries

Revision ID: 7d2f3e8c91aa
Revises: b8d3f1a2c9e4
Create Date: 2026-04-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7d2f3e8c91aa'
down_revision = 'b8d3f1a2c9e4'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('queries')}

    if 'issue_type' not in columns:
        with op.batch_alter_table('queries', schema=None) as batch_op:
            batch_op.add_column(sa.Column('issue_type', sa.String(length=100), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('queries')}

    if 'issue_type' in columns:
        with op.batch_alter_table('queries', schema=None) as batch_op:
            batch_op.drop_column('issue_type')
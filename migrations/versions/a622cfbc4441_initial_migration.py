"""Initial migration

Revision ID: a622cfbc4441
Revises: 
Create Date: 2026-03-09 19:17:21.605334

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a622cfbc4441'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('enrollments'):
        return

    columns = {col['name'] for col in inspector.get_columns('enrollments')}

    if 'payment_id' not in columns:
        with op.batch_alter_table('enrollments', schema=None) as batch_op:
            batch_op.add_column(sa.Column('payment_id', sa.String(length=120), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('enrollments'):
        return

    columns = {col['name'] for col in inspector.get_columns('enrollments')}

    if 'payment_id' in columns:
        with op.batch_alter_table('enrollments', schema=None) as batch_op:
            batch_op.drop_column('payment_id')

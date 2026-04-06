"""Add attempt fields to test submissions

Revision ID: d7a9c4e1f2ab
Revises: c4e8f2a1d9b7
Create Date: 2026-04-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7a9c4e1f2ab'
down_revision = 'c4e8f2a1d9b7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('test_submissions'):
        return

    columns = {col['name'] for col in inspector.get_columns('test_submissions')}

    with op.batch_alter_table('test_submissions', schema=None) as batch_op:
        if 'attempt_no' not in columns:
            batch_op.add_column(sa.Column('attempt_no', sa.Integer(), nullable=True, server_default='1'))
        if 'status' not in columns:
            batch_op.add_column(sa.Column('status', sa.String(length=20), nullable=True, server_default='submitted'))
        if 'score' not in columns:
            batch_op.add_column(sa.Column('score', sa.Float(), nullable=True, server_default='0'))
        if 'max_score' not in columns:
            batch_op.add_column(sa.Column('max_score', sa.Float(), nullable=True, server_default='0'))
        if 'answers_json' not in columns:
            batch_op.add_column(sa.Column('answers_json', sa.Text(), nullable=True))
        if 'started_at' not in columns:
            batch_op.add_column(sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))
        if 'ended_at' not in columns:
            batch_op.add_column(sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True))

    op.execute("UPDATE test_submissions SET attempt_no = 1 WHERE attempt_no IS NULL")
    op.execute("UPDATE test_submissions SET status = 'submitted' WHERE status IS NULL OR status = ''")
    op.execute("UPDATE test_submissions SET score = 0 WHERE score IS NULL")
    op.execute("UPDATE test_submissions SET max_score = 0 WHERE max_score IS NULL")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('test_submissions'):
        return

    columns = {col['name'] for col in inspector.get_columns('test_submissions')}

    with op.batch_alter_table('test_submissions', schema=None) as batch_op:
        if 'ended_at' in columns:
            batch_op.drop_column('ended_at')
        if 'started_at' in columns:
            batch_op.drop_column('started_at')
        if 'answers_json' in columns:
            batch_op.drop_column('answers_json')
        if 'max_score' in columns:
            batch_op.drop_column('max_score')
        if 'score' in columns:
            batch_op.drop_column('score')
        if 'status' in columns:
            batch_op.drop_column('status')
        if 'attempt_no' in columns:
            batch_op.drop_column('attempt_no')

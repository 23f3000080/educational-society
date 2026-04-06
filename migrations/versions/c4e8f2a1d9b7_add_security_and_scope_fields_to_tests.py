"""Add security and scope fields to tests

Revision ID: c4e8f2a1d9b7
Revises: 2f4a1b6d9c3e
Create Date: 2026-04-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4e8f2a1d9b7'
down_revision = '2f4a1b6d9c3e'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('tests'):
        return

    columns = {col['name'] for col in inspector.get_columns('tests')}

    with op.batch_alter_table('tests', schema=None) as batch_op:
        if 'test_scope' not in columns:
            batch_op.add_column(sa.Column('test_scope', sa.String(length=20), nullable=True, server_default='week'))
        if 'start_at' not in columns:
            batch_op.add_column(sa.Column('start_at', sa.DateTime(), nullable=True))
        if 'max_attempts' not in columns:
            batch_op.add_column(sa.Column('max_attempts', sa.Integer(), nullable=True, server_default='1'))
        if 'passcode' not in columns:
            batch_op.add_column(sa.Column('passcode', sa.String(length=40), nullable=True))
        if 'shuffle_questions' not in columns:
            batch_op.add_column(sa.Column('shuffle_questions', sa.Boolean(), nullable=True, server_default=sa.true()))
        if 'shuffle_options' not in columns:
            batch_op.add_column(sa.Column('shuffle_options', sa.Boolean(), nullable=True, server_default=sa.true()))
        if 'require_fullscreen' not in columns:
            batch_op.add_column(sa.Column('require_fullscreen', sa.Boolean(), nullable=True, server_default=sa.true()))
        if 'prevent_tab_switch' not in columns:
            batch_op.add_column(sa.Column('prevent_tab_switch', sa.Boolean(), nullable=True, server_default=sa.true()))

    op.execute("UPDATE tests SET test_scope = 'week' WHERE test_scope IS NULL OR test_scope = ''")
    op.execute("UPDATE tests SET max_attempts = 1 WHERE max_attempts IS NULL")
    op.execute("UPDATE tests SET shuffle_questions = 1 WHERE shuffle_questions IS NULL")
    op.execute("UPDATE tests SET shuffle_options = 1 WHERE shuffle_options IS NULL")
    op.execute("UPDATE tests SET require_fullscreen = 1 WHERE require_fullscreen IS NULL")
    op.execute("UPDATE tests SET prevent_tab_switch = 1 WHERE prevent_tab_switch IS NULL")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('tests'):
        return

    columns = {col['name'] for col in inspector.get_columns('tests')}

    with op.batch_alter_table('tests', schema=None) as batch_op:
        if 'prevent_tab_switch' in columns:
            batch_op.drop_column('prevent_tab_switch')
        if 'require_fullscreen' in columns:
            batch_op.drop_column('require_fullscreen')
        if 'shuffle_options' in columns:
            batch_op.drop_column('shuffle_options')
        if 'shuffle_questions' in columns:
            batch_op.drop_column('shuffle_questions')
        if 'passcode' in columns:
            batch_op.drop_column('passcode')
        if 'max_attempts' in columns:
            batch_op.drop_column('max_attempts')
        if 'start_at' in columns:
            batch_op.drop_column('start_at')
        if 'test_scope' in columns:
            batch_op.drop_column('test_scope')

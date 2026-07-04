"""Add cascade delete constraints

Revision ID: 3c1f4f6b2a91
Revises: d7a9c4e1f2ab
Create Date: 2026-07-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3c1f4f6b2a91'
down_revision = 'd7a9c4e1f2ab'
branch_labels = None
depends_on = None


CASCADE_FKS = [
    ('users_roles', ['user_id'], 'users', ['id']),
    ('users_roles', ['role_id'], 'roles', ['id']),
    ('mobile_otps', ['user_id'], 'users', ['id']),
    ('user_notifications', ['user_id'], 'users', ['id']),
    ('user_notifications', ['notification_id'], 'notifications', ['id']),
    ('enrollments', ['student_id'], 'users', ['id']),
    ('enrollments', ['course_id'], 'courses', ['id']),
    ('weeks', ['course_id'], 'courses', ['id']),
    ('videos', ['week_id'], 'weeks', ['id']),
    ('notes', ['week_id'], 'weeks', ['id']),
    ('assignments', ['course_id'], 'courses', ['id']),
    ('assignments', ['week_id'], 'weeks', ['id']),
    ('tests', ['course_id'], 'courses', ['id']),
    ('tests', ['week_id'], 'weeks', ['id']),
    ('test_questions', ['test_id'], 'tests', ['id']),
    ('test_question_options', ['question_id'], 'test_questions', ['id']),
    ('test_fill_blank_answers', ['question_id'], 'test_questions', ['id']),
    ('test_submissions', ['test_id'], 'tests', ['id']),
    ('test_submissions', ['student_id'], 'users', ['id']),
    ('questions', ['assignment_id'], 'assignments', ['id']),
    ('question_options', ['question_id'], 'questions', ['id']),
    ('fill_blank_answers', ['question_id'], 'questions', ['id']),
    ('student_answers', ['student_id'], 'users', ['id']),
    ('student_answers', ['question_id'], 'questions', ['id']),
    ('student_answers', ['selected_option_id'], 'question_options', ['id']),
    ('assignment_submissions', ['assignment_id'], 'assignments', ['id']),
    ('assignment_submissions', ['student_id'], 'users', ['id']),
    ('course_progress', ['student_id'], 'users', ['id']),
    ('course_progress', ['course_id'], 'courses', ['id']),
]


def _replace_foreign_key(table_name, constrained_columns, referred_table, referred_columns, ondelete):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_fk = next(
        (
            fk for fk in inspector.get_foreign_keys(table_name)
            if fk['constrained_columns'] == constrained_columns
            and fk['referred_table'] == referred_table
            and fk['referred_columns'] == referred_columns
        ),
        None,
    )

    if existing_fk and existing_fk.get('options', {}).get('ondelete') == ondelete:
        return

    constraint_name = existing_fk['name'] if existing_fk and existing_fk.get('name') else f"{table_name}_{'_'.join(constrained_columns)}_fkey"

    if existing_fk:
        op.drop_constraint(constraint_name, table_name, type_='foreignkey')

    create_kwargs = {}
    if ondelete is not None:
        create_kwargs['ondelete'] = ondelete

    op.create_foreign_key(
        constraint_name,
        table_name,
        referred_table,
        constrained_columns,
        referred_columns,
        **create_kwargs,
    )


def upgrade():
    for table_name, constrained_columns, referred_table, referred_columns in CASCADE_FKS:
        _replace_foreign_key(table_name, constrained_columns, referred_table, referred_columns, 'CASCADE')


def downgrade():
    for table_name, constrained_columns, referred_table, referred_columns in CASCADE_FKS:
        _replace_foreign_key(table_name, constrained_columns, referred_table, referred_columns, None)
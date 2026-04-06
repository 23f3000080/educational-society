"""Add mobile OTP table

Revision ID: b8d3f1a2c9e4
Revises: a622cfbc4441
Create Date: 2026-04-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8d3f1a2c9e4'
down_revision = 'a622cfbc4441'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('mobile_otps'):
        op.create_table(
            'mobile_otps',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('mobile_no', sa.String(length=15), nullable=False),
            sa.Column('otp', sa.String(length=6), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id')
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table('mobile_otps'):
        op.drop_table('mobile_otps')

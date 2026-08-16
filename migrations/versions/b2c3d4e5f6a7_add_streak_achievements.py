"""add streak, achievements

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-16 12:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('user_preferences', sa.Column('streak', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('user_preferences', sa.Column('max_streak', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('user_preferences', sa.Column('last_active_date', sa.String(length=10), nullable=True))
    op.create_table(
        'achievements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('telegram_user_id', sa.BigInteger(), nullable=False, index=True),
        sa.Column('code', sa.String(length=48), nullable=False),
        sa.Column('title', sa.String(length=128), nullable=False),
        sa.Column('unlocked_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_ach_user_code', 'achievements', ['telegram_user_id', 'code'])


def downgrade() -> None:
    op.drop_index('ix_ach_user_code', table_name='achievements')
    op.drop_table('achievements')
    op.drop_column('user_preferences', 'last_active_date')
    op.drop_column('user_preferences', 'max_streak')
    op.drop_column('user_preferences', 'streak')

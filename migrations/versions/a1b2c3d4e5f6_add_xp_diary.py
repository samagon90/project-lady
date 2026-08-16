"""add xp, creativity, response_length + diary_entries

Revision ID: a1b2c3d4e5f6
Revises: eea4c796ed0f
Create Date: 2026-08-16 10:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'a1b2c3d4e5f6'
down_revision = 'eea4c796ed0f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('user_preferences', sa.Column('xp', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('user_preferences', sa.Column('creativity', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('user_preferences', sa.Column('response_length', sa.Integer(), nullable=False, server_default='1'))
    op.create_table(
        'diary_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('telegram_user_id', sa.BigInteger(), nullable=False, index=True),
        sa.Column('entry_date', sa.String(length=10), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_diary_user_date', 'diary_entries', ['telegram_user_id', 'entry_date'])


def downgrade() -> None:
    op.drop_index('ix_diary_user_date', table_name='diary_entries')
    op.drop_table('diary_entries')
    op.drop_column('user_preferences', 'response_length')
    op.drop_column('user_preferences', 'creativity')
    op.drop_column('user_preferences', 'xp')

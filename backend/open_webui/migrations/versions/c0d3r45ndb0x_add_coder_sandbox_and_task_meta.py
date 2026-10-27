"""coder sandbox sessions & task meta tables

Revision ID: c0d3r45ndb0x
Revises: c0d3r4m1c7h1
Create Date: 2026-10-27

План coder.qwen.ai §A/§B/§C: таблицы для sandbox-сессий (изолированная
песочница на задачу с TTL) и метаданных задач (title/tags/pin/archive/status).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c0d3r45ndb0x'
down_revision: str | None = 'c0d3r4m1c7h1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if 'coder_sandbox_session' not in tables:
        op.create_table(
            'coder_sandbox_session',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('user_id', sa.Text(), nullable=False),
            sa.Column('mode', sa.Text(), nullable=True),
            sa.Column('status', sa.Text(), nullable=False, server_default='active'),
            sa.Column('published_share_id', sa.Text(), nullable=True),
            sa.Column('meta', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.Column('updated_at', sa.BigInteger(), nullable=False),
            sa.Column('last_active_at', sa.BigInteger(), nullable=False),
        )
        op.create_index('ix_coder_sandbox_session_user_id', 'coder_sandbox_session', ['user_id'])

    if 'coder_task_meta' not in tables:
        op.create_table(
            'coder_task_meta',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('user_id', sa.Text(), nullable=False),
            sa.Column('chat_id', sa.Text(), nullable=False),
            sa.Column('title', sa.Text(), nullable=True),
            sa.Column('tags', sa.JSON(), nullable=True),
            sa.Column('mode', sa.Text(), nullable=True),
            sa.Column('is_pinned', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('status', sa.Text(), nullable=True),
            sa.Column('meta', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.Column('updated_at', sa.BigInteger(), nullable=False),
            sa.UniqueConstraint('user_id', 'chat_id', name='uq_coder_task_meta_user_chat'),
        )
        op.create_index('ix_coder_task_meta_user_id', 'coder_task_meta', ['user_id'])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())
    if 'coder_task_meta' in tables:
        op.drop_index('ix_coder_task_meta_user_id', table_name='coder_task_meta')
        op.drop_table('coder_task_meta')
    if 'coder_sandbox_session' in tables:
        op.drop_index('ix_coder_sandbox_session_user_id', table_name='coder_sandbox_session')
        op.drop_table('coder_sandbox_session')

"""coder task meta share/fork columns

Revision ID: c0d3r45h4r1ng
Revises: c0d3r45ndb0x
Create Date: 2026-10-28

План coder.qwen.ai §C4 (публичный шеринг и fork задач): колонки публичного
шаринга в coder_task_meta — share_enabled/share_token/shared_at и ссылка на
задачу-источник forked_from.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c0d3r45h4r1ng'
down_revision: str | None = 'c0d3r45ndb0x'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())
    if 'coder_task_meta' not in tables:
        return
    cols = {c['name'] for c in inspector.get_columns('coder_task_meta')}
    if 'share_enabled' not in cols:
        op.add_column(
            'coder_task_meta',
            sa.Column('share_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if 'share_token' not in cols:
        op.add_column('coder_task_meta', sa.Column('share_token', sa.Text(), nullable=True))
    if 'shared_at' not in cols:
        op.add_column('coder_task_meta', sa.Column('shared_at', sa.BigInteger(), nullable=True))
    if 'forked_from' not in cols:
        op.add_column('coder_task_meta', sa.Column('forked_from', sa.Text(), nullable=True))
    idx = {i['name'] for i in inspector.get_indexes('coder_task_meta')}
    if 'ix_coder_task_meta_share_token' not in idx:
        op.create_index('ix_coder_task_meta_share_token', 'coder_task_meta', ['share_token'])
    # §C4 fork: привязка sandbox-сессии к задаче (id задачи из coder_task_meta),
    # чтобы копировать песочницу именно расшаренной задачи, а не последнюю сессию автора
    if 'coder_sandbox_session' in tables:
        sb_cols = {c['name'] for c in inspector.get_columns('coder_sandbox_session')}
        if 'chat_id' not in sb_cols:
            op.add_column('coder_sandbox_session', sa.Column('chat_id', sa.Text(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'coder_task_meta' not in set(inspector.get_table_names()):
        return
    idx = {i['name'] for i in inspector.get_indexes('coder_task_meta')}
    if 'ix_coder_task_meta_share_token' in idx:
        op.drop_index('ix_coder_task_meta_share_token', table_name='coder_task_meta')
    cols = {c['name'] for c in inspector.get_columns('coder_task_meta')}
    for name in ('forked_from', 'shared_at', 'share_token', 'share_enabled'):
        if name in cols:
            with op.batch_alter_table('coder_task_meta') as batch_op:
                batch_op.drop_column(name)

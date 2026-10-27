"""multi-github connections

Revision ID: c0d3r4m1c7h1
Revises: c0d3r4ud1t01
Create Date: 2026-10-27

§22.2 «Несколько GitHub-подключений»: coder_github_connection перестаёт быть
уникальным по user_id — пользователь может подключить несколько хостов
(github.com + GitHub Enterprise). Добавляются колонки github_host и is_default;
уникальность обеспечивается индексом (user_id, github_host).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c0d3r4m1c7h1'
down_revision: str | None = 'c0d3r4ud1t01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _unique_user_id_constraint() -> str | None:
    """Find the name of the UNIQUE constraint/index on (user_id) alone."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    for uc in inspector.get_unique_constraints('coder_github_connection'):
        if uc['column_names'] == ['user_id']:
            return uc['name']
    # SQLite/SQLAlchemy often materialise unique=True as an index instead
    for idx in inspector.get_indexes('coder_github_connection'):
        if idx['unique'] and idx['column_names'] == ['user_id']:
            return idx['name']
    return None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'coder_github_connection' not in set(inspector.get_table_names()):
        return

    existing_columns = {c['name'] for c in inspector.get_columns('coder_github_connection')}
    # SQLite does not support ALTER COLUMN ADD/NOT NULL directly — use batch mode
    if 'github_host' not in existing_columns:
        with op.batch_alter_table('coder_github_connection') as batch_op:
            batch_op.add_column(sa.Column('github_host', sa.Text(), nullable=True))
        op.execute("UPDATE coder_github_connection SET github_host = 'github.com' WHERE github_host IS NULL")
        with op.batch_alter_table('coder_github_connection') as batch_op:
            batch_op.alter_column('github_host', existing_type=sa.Text(), nullable=False)
    if 'is_default' not in existing_columns:
        with op.batch_alter_table('coder_github_connection') as batch_op:
            batch_op.add_column(sa.Column('is_default', sa.Boolean(), nullable=True))
        op.execute("UPDATE coder_github_connection SET is_default = 1 WHERE is_default IS NULL")
        with op.batch_alter_table('coder_github_connection') as batch_op:
            batch_op.alter_column('is_default', existing_type=sa.Boolean(), nullable=False)

    # drop the old single-connection-per-user uniqueness and add the new
    # (user_id, github_host) uniqueness. Batch mode is required because the
    # SQLite dialect does not support ALTER of constraints directly.
    name = _unique_user_id_constraint()
    with op.batch_alter_table('coder_github_connection') as batch_op:
        if name:
            try:
                batch_op.drop_constraint(name, type_='unique')
            except Exception:
                batch_op.drop_index(name)
        batch_op.create_unique_constraint(
            'uq_coder_github_connection_user_host',
            ['user_id', 'github_host'],
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'coder_github_connection' not in set(inspector.get_table_names()):
        return
    existing_uqs = {uc['name'] for uc in inspector.get_unique_constraints('coder_github_connection')}
    with op.batch_alter_table('coder_github_connection') as batch_op:
        if 'uq_coder_github_connection_user_host' in existing_uqs:
            batch_op.drop_constraint('uq_coder_github_connection_user_host', type_='unique')
        # keep one connection per user before restoring the unique constraint
        conn.exec_driver_sql(
            """
            DELETE FROM coder_github_connection
            WHERE id NOT IN (
                SELECT id FROM coder_github_connection
                WHERE rowid IN (SELECT MAX(rowid) FROM coder_github_connection GROUP BY user_id)
            )
            """
        )
        batch_op.create_unique_constraint('uq_coder_github_connection_user_id', ['user_id'])
    existing_columns = {c['name'] for c in inspector.get_columns('coder_github_connection')}
    if 'is_default' in existing_columns:
        op.drop_column('coder_github_connection', 'is_default')
    if 'github_host' in existing_columns:
        op.drop_column('coder_github_connection', 'github_host')

"""Add notification table for user notification inbox.

Revision ID: n0t1f1c4t10ns_add_table
Revises: d4e5f6a7b8c9
Create Date: 2026-11-06
"""

import sqlalchemy as sa

from alembic import op

revision: str = 'n0t1f1c4t10ns_add_table'
down_revision: str | None = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if 'notification' not in tables:
        op.create_table(
            'notification',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('user_id', sa.Text(), nullable=False, index=True),
            sa.Column('type', sa.Text(), nullable=False),
            sa.Column('title', sa.Text(), nullable=False),
            sa.Column('content', sa.Text(), nullable=True),
            sa.Column('data', sa.JSON(), nullable=True),
            sa.Column('read', sa.BigInteger(), nullable=False, default=0),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
        )

    inspector.clear_cache()


def downgrade():
    op.drop_table('notification')

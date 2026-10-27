"""add coder audit context fields

Revision ID: c0d3r4ud1t01
Revises: c0d3r4b17e21
Create Date: 2026-10-24

Adds §11.4 context fields to coder_audit_event:
correlation_id, ip_address, user_agent.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c0d3r4ud1t01'
down_revision: str | None = 'c0d3r4b17e21'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if 'coder_audit_event' not in existing_tables:
        # Coder tables created by c0d3r4b17e21 already handle this; nothing to do.
        return

    existing_columns = {c['name'] for c in inspector.get_columns('coder_audit_event')}
    if 'correlation_id' not in existing_columns:
        op.add_column('coder_audit_event', sa.Column('correlation_id', sa.Text(), nullable=True))
    if 'ip_address' not in existing_columns:
        op.add_column('coder_audit_event', sa.Column('ip_address', sa.Text(), nullable=True))
    if 'user_agent' not in existing_columns:
        op.add_column('coder_audit_event', sa.Column('user_agent', sa.Text(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'coder_audit_event' not in set(inspector.get_table_names()):
        return
    existing_columns = {c['name'] for c in inspector.get_columns('coder_audit_event')}
    if 'user_agent' in existing_columns:
        op.drop_column('coder_audit_event', 'user_agent')
    if 'ip_address' in existing_columns:
        op.drop_column('coder_audit_event', 'ip_address')
    if 'correlation_id' in existing_columns:
        op.drop_column('coder_audit_event', 'correlation_id')

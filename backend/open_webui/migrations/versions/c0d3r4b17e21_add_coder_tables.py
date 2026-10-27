"""add coder tables

Revision ID: c0d3r4b17e21
Revises: 42e2978c7933
Create Date: 2026-10-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c0d3r4b17e21'
down_revision: str | None = '42e2978c7933'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if 'coder_github_connection' not in existing_tables:
        op.create_table(
            'coder_github_connection',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('user_id', sa.Text(), nullable=False, unique=True),
            sa.Column('github_login', sa.Text(), nullable=True),
            sa.Column('github_user_id', sa.Text(), nullable=True),
            sa.Column('access_token_encrypted', sa.Text(), nullable=False),
            sa.Column('token_type', sa.Text(), nullable=False, server_default='oauth'),
            sa.Column('scopes', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.Column('updated_at', sa.BigInteger(), nullable=False),
        )
        op.create_index('ix_coder_github_connection_user_id', 'coder_github_connection', ['user_id'])

    if 'coder_project' not in existing_tables:
        op.create_table(
            'coder_project',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('user_id', sa.Text(), nullable=False),
            sa.Column('owner', sa.Text(), nullable=False),
            sa.Column('repo', sa.Text(), nullable=False),
            sa.Column('default_branch', sa.Text(), nullable=True),
            sa.Column('meta', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.Column('updated_at', sa.BigInteger(), nullable=False),
            sa.UniqueConstraint('user_id', 'owner', 'repo', name='uq_coder_project_user_repo'),
        )
        op.create_index('ix_coder_project_user_id', 'coder_project', ['user_id'])

    if 'coder_export_job' not in existing_tables:
        op.create_table(
            'coder_export_job',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('user_id', sa.Text(), nullable=False),
            sa.Column('project_id', sa.Text(), nullable=True),
            sa.Column('owner', sa.Text(), nullable=False),
            sa.Column('repo', sa.Text(), nullable=False),
            sa.Column('base_branch', sa.Text(), nullable=False),
            sa.Column('branch', sa.Text(), nullable=False),
            sa.Column('commit_message', sa.Text(), nullable=False),
            sa.Column('changeset', sa.JSON(), nullable=False),
            sa.Column('status', sa.Text(), nullable=False, server_default='pending'),
            sa.Column('error', sa.Text(), nullable=True),
            sa.Column('commit_sha', sa.Text(), nullable=True),
            sa.Column('pr_url', sa.Text(), nullable=True),
            sa.Column('pr_number', sa.Text(), nullable=True),
            sa.Column('idempotency_key', sa.Text(), nullable=False, unique=True),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.Column('updated_at', sa.BigInteger(), nullable=False),
        )
        op.create_index('ix_coder_export_job_user_id', 'coder_export_job', ['user_id'])
        op.create_index('ix_coder_export_job_status', 'coder_export_job', ['status'])

    if 'coder_audit_event' not in existing_tables:
        op.create_table(
            'coder_audit_event',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('user_id', sa.Text(), nullable=False),
            sa.Column('action', sa.Text(), nullable=False),
            sa.Column('target', sa.Text(), nullable=True),
            sa.Column('payload', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
        )
        op.create_index('ix_coder_audit_event_user_id', 'coder_audit_event', ['user_id'])
        op.create_index('ix_coder_audit_event_created_at', 'coder_audit_event', ['created_at'])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    for table in (
        'coder_audit_event',
        'coder_export_job',
        'coder_project',
        'coder_github_connection',
    ):
        if table in existing_tables:
            op.drop_table(table)

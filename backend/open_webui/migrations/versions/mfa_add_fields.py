"""Add MFA fields to user table.

Revision ID: mfa_add_fields
Revises: n0t1f1c4t10ns_add_table
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from alembic import op

revision: str = 'mfa_add_fields'
down_revision: str | None = 'n0t1f1c4t10ns_add_table'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('user')]

    if 'mfa_secret' not in columns:
        op.add_column('user', sa.Column('mfa_secret', sa.Text(), nullable=True))

    if 'mfa_enabled' not in columns:
        op.add_column('user', sa.Column('mfa_enabled', sa.BigInteger(), nullable=False, default=0))

    if 'mfa_backup_codes' not in columns:
        op.add_column('user', sa.Column('mfa_backup_codes', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('user', 'mfa_backup_codes')
    op.drop_column('user', 'mfa_enabled')
    op.drop_column('user', 'mfa_secret')

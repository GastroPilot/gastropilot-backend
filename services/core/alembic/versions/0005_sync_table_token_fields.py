"""Sync table token columns with current Table ORM model.

Revision ID: 0005_sync_table_token
Revises: 0004_sync_restaurant_billing
Create Date: 2026-03-13
"""

from __future__ import annotations

from alembic import op

revision = "0005_sync_table_token"
down_revision = "0004_sync_restaurant_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tables ADD COLUMN IF NOT EXISTS table_token VARCHAR(64)")
    op.execute("ALTER TABLE tables ADD COLUMN IF NOT EXISTS token_created_at TIMESTAMPTZ")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tables_table_token ON tables(table_token)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tables_table_token")
    op.execute("ALTER TABLE tables DROP COLUMN IF EXISTS token_created_at")
    op.execute("ALTER TABLE tables DROP COLUMN IF EXISTS table_token")

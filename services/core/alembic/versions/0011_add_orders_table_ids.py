"""Add table_ids to orders for grouped table occupancy.

Revision ID: 0011_orders_table_ids
Revises: 0010_orders_schema_sync
Create Date: 2026-03-23
"""

from __future__ import annotations

from alembic import op

revision = "0011_orders_table_ids"
down_revision = "0010_orders_schema_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS table_ids JSONB")
    op.execute("""
        UPDATE orders
        SET table_ids = jsonb_build_array(table_id)
        WHERE table_id IS NOT NULL
          AND (
            table_ids IS NULL
            OR jsonb_typeof(table_ids) <> 'array'
            OR table_ids = '[]'::jsonb
          )
        """)


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS table_ids")

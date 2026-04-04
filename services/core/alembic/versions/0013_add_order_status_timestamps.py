"""Add order status transition timestamps for kitchen/service tracking.

Revision ID: 0013_order_status_timestamps
Revises: 0012_table_day_config_area
Create Date: 2026-04-04
"""

from __future__ import annotations

from alembic import op

revision = "0013_order_status_timestamps"
down_revision = "0012_table_day_config_area"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS sent_to_kitchen_at TIMESTAMPTZ")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS in_preparation_at TIMESTAMPTZ")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS ready_at TIMESTAMPTZ")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS served_at TIMESTAMPTZ")

    # Best-effort backfill for existing rows based on current status.
    op.execute("""
        UPDATE orders
        SET sent_to_kitchen_at = opened_at
        WHERE sent_to_kitchen_at IS NULL
          AND status IN ('sent_to_kitchen', 'in_preparation', 'ready', 'served', 'paid', 'canceled')
        """)
    op.execute("""
        UPDATE orders
        SET in_preparation_at = COALESCE(sent_to_kitchen_at, opened_at)
        WHERE in_preparation_at IS NULL
          AND status IN ('in_preparation', 'ready', 'served', 'paid', 'canceled')
        """)
    op.execute("""
        UPDATE orders
        SET ready_at = COALESCE(in_preparation_at, sent_to_kitchen_at, opened_at)
        WHERE ready_at IS NULL
          AND status IN ('ready', 'served', 'paid', 'canceled')
        """)
    op.execute("""
        UPDATE orders
        SET served_at = COALESCE(ready_at, in_preparation_at, sent_to_kitchen_at, opened_at)
        WHERE served_at IS NULL
          AND status IN ('served', 'paid')
        """)


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS served_at")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS ready_at")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS in_preparation_at")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS sent_to_kitchen_at")

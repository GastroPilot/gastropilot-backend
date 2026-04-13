"""Add kitchen ticket tracking fields for order items.

Revision ID: 0015_order_item_kitchen_tickets
Revises: 0014_menu_category_type
Create Date: 2026-04-05
"""

from __future__ import annotations

from alembic import op

revision = "0015_order_item_kitchen_tickets"
down_revision = "0014_menu_category_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Sequence counter on order-level to issue monotonically increasing kitchen tickets.
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS kitchen_ticket_seq INTEGER NOT NULL DEFAULT 0"
    )

    # Item-level kitchen delivery tracking.
    op.execute("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS kitchen_ticket_no INTEGER")
    op.execute("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS sent_to_kitchen_at TIMESTAMPTZ")

    # Best-effort backfill for already sent/processed items.
    op.execute("""
        UPDATE order_items
        SET kitchen_ticket_no = 1
        WHERE kitchen_ticket_no IS NULL
          AND status IN ('sent', 'in_preparation', 'ready', 'served')
        """)
    op.execute("""
        UPDATE order_items AS oi
        SET sent_to_kitchen_at = COALESCE(o.sent_to_kitchen_at, o.opened_at, NOW())
        FROM orders AS o
        WHERE oi.order_id = o.id
          AND oi.sent_to_kitchen_at IS NULL
          AND oi.status IN ('sent', 'in_preparation', 'ready', 'served')
        """)

    # Ensure sequence baseline reflects existing backfilled tickets.
    op.execute("""
        UPDATE orders AS o
        SET kitchen_ticket_seq = COALESCE(max_ticket.max_ticket_no, 0)
        FROM (
            SELECT order_id, MAX(kitchen_ticket_no) AS max_ticket_no
            FROM order_items
            GROUP BY order_id
        ) AS max_ticket
        WHERE o.id = max_ticket.order_id
          AND COALESCE(o.kitchen_ticket_seq, 0) < COALESCE(max_ticket.max_ticket_no, 0)
        """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_items_order_id_kitchen_ticket_no "
        "ON order_items(order_id, kitchen_ticket_no)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_order_items_order_id_kitchen_ticket_no")
    op.execute("ALTER TABLE order_items DROP COLUMN IF EXISTS sent_to_kitchen_at")
    op.execute("ALTER TABLE order_items DROP COLUMN IF EXISTS kitchen_ticket_no")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS kitchen_ticket_seq")

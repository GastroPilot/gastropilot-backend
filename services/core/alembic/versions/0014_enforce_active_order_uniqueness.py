"""Enforce one active order per reservation/table.

Revision ID: 0014_active_order_uniqueness
Revises: 0013_order_status_timestamps
Create Date: 2026-04-04
"""

from __future__ import annotations

from alembic import op

revision = "0014_active_order_uniqueness"
down_revision = "0013_order_status_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            duplicate_reservation_groups INTEGER;
            duplicate_table_groups INTEGER;
        BEGIN
            SELECT COUNT(*)
            INTO duplicate_reservation_groups
            FROM (
                SELECT tenant_id, reservation_id
                FROM orders
                WHERE reservation_id IS NOT NULL
                  AND status NOT IN ('paid', 'canceled')
                  AND payment_status <> 'paid'
                GROUP BY tenant_id, reservation_id
                HAVING COUNT(*) > 1
            ) conflicts;

            IF duplicate_reservation_groups > 0 THEN
                RAISE EXCEPTION
                    'Migration aborted: % duplicate active reservation-order groups found. Resolve duplicates in orders first.',
                    duplicate_reservation_groups;
            END IF;

            SELECT COUNT(*)
            INTO duplicate_table_groups
            FROM (
                SELECT tenant_id, table_id
                FROM orders
                WHERE table_id IS NOT NULL
                  AND status NOT IN ('paid', 'canceled')
                  AND payment_status <> 'paid'
                GROUP BY tenant_id, table_id
                HAVING COUNT(*) > 1
            ) conflicts;

            IF duplicate_table_groups > 0 THEN
                RAISE EXCEPTION
                    'Migration aborted: % duplicate active table-order groups found. Resolve duplicates in orders first.',
                    duplicate_table_groups;
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_active_reservation
        ON orders(tenant_id, reservation_id)
        WHERE reservation_id IS NOT NULL
          AND status NOT IN ('paid', 'canceled')
          AND payment_status <> 'paid'
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_active_table
        ON orders(tenant_id, table_id)
        WHERE table_id IS NOT NULL
          AND status NOT IN ('paid', 'canceled')
          AND payment_status <> 'paid'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_orders_active_table")
    op.execute("DROP INDEX IF EXISTS uq_orders_active_reservation")

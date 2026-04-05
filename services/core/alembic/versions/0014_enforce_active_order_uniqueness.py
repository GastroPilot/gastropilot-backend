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
    op.execute("""
        DO $$
        DECLARE
            canceled_by_reservation INTEGER := 0;
            canceled_by_table INTEGER := 0;
        BEGIN
            WITH ranked_duplicates AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY tenant_id, reservation_id
                        ORDER BY
                            COALESCE(opened_at, created_at) DESC,
                            created_at DESC,
                            id DESC
                    ) AS row_num
                FROM orders
                WHERE reservation_id IS NOT NULL
                  AND status NOT IN ('paid', 'canceled')
                  AND payment_status <> 'paid'
            )
            UPDATE orders AS o
            SET
                status = 'canceled',
                closed_at = COALESCE(o.closed_at, NOW()),
                notes = CASE
                    WHEN o.notes IS NULL OR o.notes = '' THEN
                        '[system] Auto-canceled by migration 0014 (duplicate active reservation order).'
                    WHEN POSITION('[system] Auto-canceled by migration 0014' IN o.notes) > 0 THEN
                        o.notes
                    ELSE
                        o.notes || E'\n[system] Auto-canceled by migration 0014 (duplicate active reservation order).'
                END
            FROM ranked_duplicates AS d
            WHERE o.id = d.id
              AND d.row_num > 1;

            GET DIAGNOSTICS canceled_by_reservation = ROW_COUNT;

            WITH ranked_duplicates AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY tenant_id, table_id
                        ORDER BY
                            COALESCE(opened_at, created_at) DESC,
                            created_at DESC,
                            id DESC
                    ) AS row_num
                FROM orders
                WHERE table_id IS NOT NULL
                  AND status NOT IN ('paid', 'canceled')
                  AND payment_status <> 'paid'
            )
            UPDATE orders AS o
            SET
                status = 'canceled',
                closed_at = COALESCE(o.closed_at, NOW()),
                notes = CASE
                    WHEN o.notes IS NULL OR o.notes = '' THEN
                        '[system] Auto-canceled by migration 0014 (duplicate active table order).'
                    WHEN POSITION('[system] Auto-canceled by migration 0014' IN o.notes) > 0 THEN
                        o.notes
                    ELSE
                        o.notes || E'\n[system] Auto-canceled by migration 0014 (duplicate active table order).'
                END
            FROM ranked_duplicates AS d
            WHERE o.id = d.id
              AND d.row_num > 1;

            GET DIAGNOSTICS canceled_by_table = ROW_COUNT;

            RAISE NOTICE
                'Migration 0014 deduplication: canceled % orders by reservation and % orders by table.',
                canceled_by_reservation,
                canceled_by_table;
        END
        $$;
        """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_active_reservation
        ON orders(tenant_id, reservation_id)
        WHERE reservation_id IS NOT NULL
          AND status NOT IN ('paid', 'canceled')
          AND payment_status <> 'paid'
        """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_active_table
        ON orders(tenant_id, table_id)
        WHERE table_id IS NOT NULL
          AND status NOT IN ('paid', 'canceled')
          AND payment_status <> 'paid'
        """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_orders_active_table")
    op.execute("DROP INDEX IF EXISTS uq_orders_active_reservation")

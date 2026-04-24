"""Add indexes to speed up order statistics aggregations.

Revision ID: 0025_orders_statistics_indexes
Revises: 0024_reservation_invites
Create Date: 2026-04-22
"""

from __future__ import annotations

from alembic import op

revision = "0025_orders_statistics_indexes"
down_revision = "0024_reservation_invites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Partial covering index for statistics endpoints that filter paid orders by paid_at range.
    # Covers:
    # - revenue stats (sum/avg over total/tip/discount)
    # - hourly stats (opened_at + total)
    # - top-items/category (order id join key to order_items)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_orders_stats_paid_at_cover
        ON orders (paid_at)
        INCLUDE (id, opened_at, total, tip_amount, discount_amount)
        WHERE payment_status = 'paid'
          AND paid_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_orders_stats_paid_at_cover")


"""Add selected_menu_deal_id to orders.

Revision ID: 0029_menu_deal_order_ref
Revises: 0028_extend_upsell_menu_deals
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op

revision = "0029_menu_deal_order_ref"
down_revision = "0028_extend_upsell_menu_deals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS selected_menu_deal_id UUID")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_selected_menu_deal_id ON orders(selected_menu_deal_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_orders_selected_menu_deal_id")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS selected_menu_deal_id")

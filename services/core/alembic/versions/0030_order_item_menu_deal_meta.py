"""Persist menu deal metadata on order items.

Revision ID: 0030_order_item_deal_meta
Revises: 0029_menu_deal_order_ref
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op

revision = "0030_order_item_deal_meta"
down_revision = "0029_menu_deal_order_ref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS menu_deal_id UUID")
    op.execute(
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS menu_deal_name VARCHAR(200)"
    )
    op.execute(
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS menu_deal_component_label VARCHAR(200)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_items_menu_deal_id ON order_items(menu_deal_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_order_items_menu_deal_id")
    op.execute("ALTER TABLE order_items DROP COLUMN IF EXISTS menu_deal_component_label")
    op.execute("ALTER TABLE order_items DROP COLUMN IF EXISTS menu_deal_name")
    op.execute("ALTER TABLE order_items DROP COLUMN IF EXISTS menu_deal_id")

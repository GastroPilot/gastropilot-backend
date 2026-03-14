"""Sync orders/order_items columns required by Orders service ORM.

Revision ID: 0010_orders_schema_sync
Revises: 0009_add_orders_guest_allergens
Create Date: 2026-03-14
"""

from __future__ import annotations

from alembic import op

revision = "0010_orders_schema_sync"
down_revision = "0009_add_orders_guest_allergens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # orders table parity
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS guest_id UUID")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS reservation_id UUID")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS party_size INTEGER")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS subtotal DOUBLE PRECISION NOT NULL DEFAULT 0")
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS tax_amount_7 DOUBLE PRECISION NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS tax_amount_19 DOUBLE PRECISION NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS tax_amount DOUBLE PRECISION NOT NULL DEFAULT 0")
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_amount DOUBLE PRECISION NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS tip_amount DOUBLE PRECISION NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS total DOUBLE PRECISION NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(32)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS split_payments JSONB")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS special_requests TEXT")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_by_user_id UUID")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_percentage DOUBLE PRECISION")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS guest_allergens JSONB")

    # order_items table parity (this fixes the reported 500 on missing `course`)
    op.execute("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS menu_item_id UUID")
    op.execute("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS item_name VARCHAR(200)")
    op.execute("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS item_description TEXT")
    op.execute("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS category VARCHAR(100)")
    op.execute(
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS quantity INTEGER NOT NULL DEFAULT 1"
    )
    op.execute("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS unit_price DOUBLE PRECISION")
    op.execute("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS total_price DOUBLE PRECISION")
    op.execute(
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS tax_rate DOUBLE PRECISION NOT NULL DEFAULT 0.19"
    )
    op.execute("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS notes TEXT")
    op.execute(
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS course INTEGER DEFAULT 1")
    op.execute("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS allergens JSONB")
    op.execute(
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
    )
    op.execute(
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
    )

    # legacy column backfill where applicable
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'orders' AND column_name = 'created_by'
            ) THEN
                UPDATE orders
                SET created_by_user_id = created_by
                WHERE created_by_user_id IS NULL AND created_by IS NOT NULL;
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'order_items' AND column_name = 'name'
            ) THEN
                UPDATE order_items
                SET item_name = name
                WHERE item_name IS NULL AND name IS NOT NULL;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'order_items' AND column_name = 'price'
            ) THEN
                UPDATE order_items
                SET unit_price = price
                WHERE unit_price IS NULL AND price IS NOT NULL;
            END IF;
        END
        $$;
        """
    )

    op.execute(
        "UPDATE order_items SET total_price = COALESCE(unit_price, 0) * COALESCE(quantity, 1) WHERE total_price IS NULL"
    )
    op.execute("UPDATE order_items SET tax_rate = 0.19 WHERE tax_rate IS NULL")
    op.execute("UPDATE order_items SET sort_order = 0 WHERE sort_order IS NULL")
    op.execute("UPDATE order_items SET course = 1 WHERE course IS NULL")
    op.execute("UPDATE order_items SET allergens = '[]'::jsonb WHERE allergens IS NULL")

    op.execute("CREATE INDEX IF NOT EXISTS ix_orders_opened_at ON orders(opened_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_order_items_order_id ON order_items(order_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_order_items_order_id")
    op.execute("DROP INDEX IF EXISTS ix_orders_opened_at")

"""Extend upsell packages for menu deal bundles.

Revision ID: 0028_extend_upsell_menu_deals
Revises: 0027_extend_vouchers_offers
Create Date: 2026-04-25
"""

from __future__ import annotations

from alembic import op

revision = "0028_extend_upsell_menu_deals"
down_revision = "0027_extend_vouchers_offers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE upsell_packages ADD COLUMN IF NOT EXISTS package_type VARCHAR(24) NOT NULL DEFAULT 'addon'"
    )
    op.execute(
        "ALTER TABLE upsell_packages ADD COLUMN IF NOT EXISTS pricing_mode VARCHAR(32) NOT NULL DEFAULT 'fixed_price'"
    )
    op.execute(
        "ALTER TABLE upsell_packages ADD COLUMN IF NOT EXISTS service_period VARCHAR(32) NOT NULL DEFAULT 'all'"
    )
    op.execute("ALTER TABLE upsell_packages ADD COLUMN IF NOT EXISTS valid_time_from TIME")
    op.execute("ALTER TABLE upsell_packages ADD COLUMN IF NOT EXISTS valid_time_until TIME")
    op.execute("ALTER TABLE upsell_packages ADD COLUMN IF NOT EXISTS component_rules JSONB")
    op.execute(
        "ALTER TABLE upsell_packages ADD COLUMN IF NOT EXISTS allow_main_item_surcharge BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute("ALTER TABLE upsell_packages ADD COLUMN IF NOT EXISTS main_item_base_price FLOAT")

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_upsell_packages_package_type ON upsell_packages(package_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_upsell_packages_service_period ON upsell_packages(service_period)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_upsell_packages_service_period")
    op.execute("DROP INDEX IF EXISTS idx_upsell_packages_package_type")
    op.execute("ALTER TABLE upsell_packages DROP COLUMN IF EXISTS main_item_base_price")
    op.execute("ALTER TABLE upsell_packages DROP COLUMN IF EXISTS allow_main_item_surcharge")
    op.execute("ALTER TABLE upsell_packages DROP COLUMN IF EXISTS component_rules")
    op.execute("ALTER TABLE upsell_packages DROP COLUMN IF EXISTS valid_time_until")
    op.execute("ALTER TABLE upsell_packages DROP COLUMN IF EXISTS valid_time_from")
    op.execute("ALTER TABLE upsell_packages DROP COLUMN IF EXISTS service_period")
    op.execute("ALTER TABLE upsell_packages DROP COLUMN IF EXISTS pricing_mode")
    op.execute("ALTER TABLE upsell_packages DROP COLUMN IF EXISTS package_type")

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
    # Self-heal for environments bootstrapped via install/sql/init.sql + alembic stamp,
    # where 0003_add_missing_models never executed because init.sql historically did not
    # contain the upsell_packages table. Schema mirrors 0003 exactly.
    op.execute("""
        CREATE TABLE IF NOT EXISTS upsell_packages (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
            name VARCHAR(240) NOT NULL,
            description TEXT,
            price FLOAT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            available_from_date DATE,
            available_until_date DATE,
            min_party_size INTEGER,
            max_party_size INTEGER,
            available_times JSONB,
            available_weekdays JSONB,
            image_url VARCHAR(512),
            display_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_upsell_packages_tenant_id ON upsell_packages(tenant_id)"
    )

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

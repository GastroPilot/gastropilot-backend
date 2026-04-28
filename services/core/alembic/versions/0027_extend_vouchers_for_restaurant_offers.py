"""Extend vouchers with restaurant offer rules and tenant-scoped code uniqueness.

Revision ID: 0027_extend_vouchers_offers
Revises: 0026_drop_res_special_requests
Create Date: 2026-04-25
"""

from __future__ import annotations

from alembic import op

revision = "0027_extend_vouchers_offers"
down_revision = "0026_drop_res_special_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Self-heal for environments bootstrapped via install/sql/init.sql + alembic stamp,
    # where 0003_add_missing_models never executed because init.sql historically did not
    # contain the vouchers/voucher_usage tables. Schema mirrors 0003 exactly.
    op.execute("""
        CREATE TABLE IF NOT EXISTS vouchers (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
            code VARCHAR(64) UNIQUE NOT NULL,
            name VARCHAR(240),
            description TEXT,
            type VARCHAR(32) NOT NULL DEFAULT 'fixed',
            value FLOAT NOT NULL,
            valid_from DATE,
            valid_until DATE,
            max_uses INTEGER,
            used_count INTEGER NOT NULL DEFAULT 0,
            min_order_value FLOAT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_vouchers_tenant_id ON vouchers(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_vouchers_code ON vouchers(code)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS voucher_usage (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            voucher_id UUID NOT NULL REFERENCES vouchers(id) ON DELETE CASCADE,
            reservation_id UUID REFERENCES reservations(id) ON DELETE SET NULL,
            tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
            used_by_email VARCHAR(255),
            discount_amount FLOAT NOT NULL,
            used_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_voucher_usage_tenant_id ON voucher_usage(tenant_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_voucher_usage_voucher_id ON voucher_usage(voucher_id)"
    )

    op.execute(
        "ALTER TABLE vouchers ADD COLUMN IF NOT EXISTS applies_to VARCHAR(32) NOT NULL DEFAULT 'all'"
    )
    op.execute("ALTER TABLE vouchers ADD COLUMN IF NOT EXISTS valid_weekdays JSONB")
    op.execute("ALTER TABLE vouchers ADD COLUMN IF NOT EXISTS valid_time_from TIME")
    op.execute("ALTER TABLE vouchers ADD COLUMN IF NOT EXISTS valid_time_until TIME")

    # Change uniqueness from global code to per-restaurant code.
    op.execute("ALTER TABLE vouchers DROP CONSTRAINT IF EXISTS vouchers_code_key")
    op.execute("DROP INDEX IF EXISTS uq_vouchers_tenant_code")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_vouchers_tenant_code ON vouchers(tenant_id, code)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_vouchers_tenant_code")
    op.execute("ALTER TABLE vouchers ADD CONSTRAINT vouchers_code_key UNIQUE (code)")
    op.execute("ALTER TABLE vouchers DROP COLUMN IF EXISTS valid_time_until")
    op.execute("ALTER TABLE vouchers DROP COLUMN IF EXISTS valid_time_from")
    op.execute("ALTER TABLE vouchers DROP COLUMN IF EXISTS valid_weekdays")
    op.execute("ALTER TABLE vouchers DROP COLUMN IF EXISTS applies_to")

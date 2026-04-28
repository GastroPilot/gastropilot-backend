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

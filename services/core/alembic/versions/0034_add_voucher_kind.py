"""Add voucher kind for separating discounts and vouchers.

Revision ID: 0034_add_voucher_kind
Revises: 0033_allergens_jsonb
Create Date: 2026-04-29
"""

from __future__ import annotations

from alembic import op

revision = "0034_add_voucher_kind"
down_revision = "0033_allergens_jsonb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE vouchers ADD COLUMN IF NOT EXISTS kind VARCHAR(16)")
    op.execute("UPDATE vouchers SET kind = 'discount' WHERE kind IS NULL")
    op.execute("ALTER TABLE vouchers ALTER COLUMN kind SET DEFAULT 'discount'")
    op.execute("ALTER TABLE vouchers ALTER COLUMN kind SET NOT NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_vouchers_kind'
            ) THEN
                ALTER TABLE vouchers
                ADD CONSTRAINT ck_vouchers_kind
                CHECK (kind IN ('discount','voucher'));
            END IF;
        END$$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE vouchers DROP CONSTRAINT IF EXISTS ck_vouchers_kind")
    op.execute("ALTER TABLE vouchers DROP COLUMN IF EXISTS kind")

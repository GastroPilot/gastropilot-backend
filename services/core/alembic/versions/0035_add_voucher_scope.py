"""Add voucher scope for public/individual offers.

Revision ID: 0035_add_voucher_scope
Revises: 0034_add_voucher_kind
Create Date: 2026-04-29
"""

from __future__ import annotations

from alembic import op

revision = "0035_add_voucher_scope"
down_revision = "0034_add_voucher_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE vouchers ADD COLUMN IF NOT EXISTS scope VARCHAR(16)")
    op.execute("UPDATE vouchers SET scope = 'public' WHERE scope IS NULL")
    op.execute("ALTER TABLE vouchers ALTER COLUMN scope SET DEFAULT 'public'")
    op.execute("ALTER TABLE vouchers ALTER COLUMN scope SET NOT NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_vouchers_scope'
            ) THEN
                ALTER TABLE vouchers
                ADD CONSTRAINT ck_vouchers_scope
                CHECK (scope IN ('public','individual'));
            END IF;
        END$$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE vouchers DROP CONSTRAINT IF EXISTS ck_vouchers_scope")
    op.execute("ALTER TABLE vouchers DROP COLUMN IF EXISTS scope")

"""Add remaining value tracking for voucher balances.

Revision ID: 0036_add_voucher_remaining_value
Revises: 0035_add_voucher_scope
Create Date: 2026-04-29
"""

from __future__ import annotations

from alembic import op

revision = "0036_add_voucher_remaining_value"
down_revision = "0035_add_voucher_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE vouchers ADD COLUMN IF NOT EXISTS remaining_value DOUBLE PRECISION")
    op.execute(
        """
        UPDATE vouchers
        SET remaining_value = CASE
            WHEN kind = 'voucher' THEN
                CASE
                    WHEN used_count > 0 THEN 0
                    ELSE value
                END
            ELSE NULL
        END
        WHERE remaining_value IS NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE vouchers DROP COLUMN IF EXISTS remaining_value")

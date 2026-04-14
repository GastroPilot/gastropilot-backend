"""Add business fields to restaurants for legal compliance (AO/UStG).

Revision ID: 0022_restaurant_business_fields
Revises: 0021_closing_is_automatic
Create Date: 2026-04-14
"""

from __future__ import annotations

from alembic import op

revision = "0022_restaurant_business_fields"
down_revision = "0021_closing_is_automatic"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS "
        "company_name VARCHAR(300)"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS "
        "street VARCHAR(200)"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS "
        "zip_code VARCHAR(10)"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS "
        "city VARCHAR(100)"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS "
        "country VARCHAR(3) DEFAULT 'DE'"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS "
        "tax_number VARCHAR(30)"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS "
        "vat_id VARCHAR(20)"
    )


def downgrade() -> None:
    for col in ("company_name", "street", "zip_code", "city", "country", "tax_number", "vat_id"):
        op.execute(f"ALTER TABLE restaurants DROP COLUMN IF EXISTS {col}")

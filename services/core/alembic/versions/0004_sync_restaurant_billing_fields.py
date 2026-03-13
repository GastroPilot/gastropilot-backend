"""Sync restaurants billing/subscription columns with current ORM model.

Revision ID: 0004_sync_restaurant_billing
Revises: 0003_missing_models
Create Date: 2026-03-13
"""

from __future__ import annotations

from alembic import op

revision = "0004_sync_restaurant_billing"
down_revision = "0003_missing_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep this migration idempotent across local DB variants (init.sql, partial Alembic states).
    op.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(128)")
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(128)"
    )
    op.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS stripe_price_id VARCHAR(128)")
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(32) DEFAULT 'inactive'"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS subscription_current_period_end TIMESTAMPTZ"
    )
    op.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS billing_email VARCHAR(255)")
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS subscription_tier VARCHAR(32) DEFAULT 'free'"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS is_featured BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS featured_until TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS featured_until")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS is_featured")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS is_suspended")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS subscription_tier")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS billing_email")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS subscription_current_period_end")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS subscription_status")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS stripe_price_id")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS stripe_subscription_id")
    op.execute("ALTER TABLE restaurants DROP COLUMN IF EXISTS stripe_customer_id")

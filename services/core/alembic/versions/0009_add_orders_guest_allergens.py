"""Add guest_allergens column to orders.

Revision ID: 0009_add_orders_guest_allergens
Revises: 0008_sync_remaining_core_models
Create Date: 2026-03-14
"""

from __future__ import annotations

from alembic import op

revision = "0009_add_orders_guest_allergens"
down_revision = "0008_sync_remaining_core_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS guest_allergens JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS guest_allergens")

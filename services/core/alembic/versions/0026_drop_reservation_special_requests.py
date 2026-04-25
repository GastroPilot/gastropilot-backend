"""Drop legacy special_requests column from reservations.

Revision ID: 0026_drop_res_special_requests
Revises: 0025_orders_statistics_indexes
Create Date: 2026-04-25
"""

from __future__ import annotations

from alembic import op

revision = "0026_drop_res_special_requests"
down_revision = "0025_orders_statistics_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE reservations DROP COLUMN IF EXISTS special_requests")


def downgrade() -> None:
    op.execute("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS special_requests TEXT")

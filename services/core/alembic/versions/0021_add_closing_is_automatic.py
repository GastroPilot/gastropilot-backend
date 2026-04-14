"""Add is_automatic flag to fiskaly_cash_point_closings.

Revision ID: 0021_closing_is_automatic
Revises: 0020_fiskaly_cash_point_closings
Create Date: 2026-04-14
"""

from __future__ import annotations

from alembic import op

revision = "0021_closing_is_automatic"
down_revision = "0020_fiskaly_cash_point_closings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE fiskaly_cash_point_closings "
        "ADD COLUMN IF NOT EXISTS is_automatic BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE fiskaly_cash_point_closings DROP COLUMN IF EXISTS is_automatic"
    )

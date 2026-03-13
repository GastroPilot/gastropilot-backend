"""Sync reservation reminder flag with current Reservation ORM model.

Revision ID: 0006_sync_reservation_reminder
Revises: 0005_sync_table_token
Create Date: 2026-03-13
"""

from __future__ import annotations

from alembic import op

revision = "0006_sync_reservation_reminder"
down_revision = "0005_sync_table_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS reminder_sent BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE reservations DROP COLUMN IF EXISTS reminder_sent")

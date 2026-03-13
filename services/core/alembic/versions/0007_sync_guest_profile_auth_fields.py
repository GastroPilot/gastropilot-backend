"""Sync guest profile auth-related columns with current GuestProfile ORM model.

Revision ID: 0007_sync_guest_profile_auth
Revises: 0006_sync_reservation_reminder
Create Date: 2026-03-13
"""

from __future__ import annotations

from alembic import op

revision = "0007_sync_guest_profile_auth"
down_revision = "0006_sync_reservation_reminder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE guest_profiles ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)")
    op.execute(
        "ALTER TABLE guest_profiles ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE guest_profiles ADD COLUMN IF NOT EXISTS email_verification_token VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE guest_profiles ADD COLUMN IF NOT EXISTS allergen_profile JSONB DEFAULT '[]'"
    )
    op.execute("ALTER TABLE guest_profiles ADD COLUMN IF NOT EXISTS push_token VARCHAR(512)")


def downgrade() -> None:
    op.execute("ALTER TABLE guest_profiles DROP COLUMN IF EXISTS push_token")
    op.execute("ALTER TABLE guest_profiles DROP COLUMN IF EXISTS allergen_profile")
    op.execute("ALTER TABLE guest_profiles DROP COLUMN IF EXISTS email_verification_token")
    op.execute("ALTER TABLE guest_profiles DROP COLUMN IF EXISTS email_verified")
    op.execute("ALTER TABLE guest_profiles DROP COLUMN IF EXISTS password_hash")

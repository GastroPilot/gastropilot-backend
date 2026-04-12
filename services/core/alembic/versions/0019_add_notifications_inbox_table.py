"""Add notifications inbox table used by public guest endpoints.

Revision ID: 0019_notifications_inbox
Revises: 0018_fiskaly_org_credentials
Create Date: 2026-04-12
"""

from __future__ import annotations

from alembic import op

revision = "0019_notifications_inbox"
down_revision = "0018_fiskaly_org_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            guest_profile_id UUID NOT NULL REFERENCES guest_profiles(id) ON DELETE CASCADE,
            tenant_id UUID REFERENCES restaurants(id) ON DELETE SET NULL,
            type VARCHAR(64) NOT NULL,
            title VARCHAR(255) NOT NULL,
            body TEXT,
            data JSONB DEFAULT '{}',
            is_read BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_guest_profile_id "
        "ON notifications(guest_profile_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_created_at "
        "ON notifications(created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_notifications_created_at")
    op.execute("DROP INDEX IF EXISTS idx_notifications_guest_profile_id")
    op.execute("DROP TABLE IF EXISTS notifications")

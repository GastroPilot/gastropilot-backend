"""Sync remaining frequently used core models for local schema parity.

Revision ID: 0008_sync_remaining_core_models
Revises: 0007_sync_guest_profile_auth
Create Date: 2026-03-13
"""

from __future__ import annotations

from alembic import op

revision = "0008_sync_remaining_core_models"
down_revision = "0007_sync_guest_profile_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Waitlist: public tracking endpoints use this token
    op.execute("ALTER TABLE waitlist ADD COLUMN IF NOT EXISTS tracking_token VARCHAR(64)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_waitlist_tracking_token ON waitlist(tracking_token)")

    # Devices
    op.execute("""
    CREATE TABLE IF NOT EXISTS devices (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
        name VARCHAR(100) NOT NULL,
        station VARCHAR(50) NOT NULL DEFAULT 'alle',
        device_token VARCHAR(128) NOT NULL UNIQUE,
        last_seen_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_devices_tenant_id ON devices(tenant_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_device_token ON devices(device_token)")

    # Reviews
    op.execute("""
    CREATE TABLE IF NOT EXISTS reviews (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
        guest_profile_id UUID NOT NULL REFERENCES guest_profiles(id) ON DELETE CASCADE,
        rating INTEGER NOT NULL,
        title VARCHAR(200),
        text TEXT,
        is_visible BOOLEAN NOT NULL DEFAULT TRUE,
        is_verified BOOLEAN NOT NULL DEFAULT FALSE,
        staff_reply TEXT,
        staff_reply_at TIMESTAMPTZ,
        staff_reply_by UUID REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_reviews_tenant_id ON reviews(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_reviews_guest_profile_id ON reviews(guest_profile_id)")

    # Guest favorites
    op.execute("""
    CREATE TABLE IF NOT EXISTS guest_favorites (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        guest_profile_id UUID NOT NULL REFERENCES guest_profiles(id) ON DELETE CASCADE,
        restaurant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_guest_favorites_unique ON guest_favorites(guest_profile_id, restaurant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_guest_favorites_guest_profile_id ON guest_favorites(guest_profile_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_guest_favorites_restaurant_id ON guest_favorites(restaurant_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_guest_favorites_restaurant_id")
    op.execute("DROP INDEX IF EXISTS idx_guest_favorites_guest_profile_id")
    op.execute("DROP INDEX IF EXISTS idx_guest_favorites_unique")
    op.execute("DROP TABLE IF EXISTS guest_favorites")

    op.execute("DROP INDEX IF EXISTS idx_reviews_guest_profile_id")
    op.execute("DROP INDEX IF EXISTS idx_reviews_tenant_id")
    op.execute("DROP TABLE IF EXISTS reviews")

    op.execute("DROP INDEX IF EXISTS idx_devices_device_token")
    op.execute("DROP INDEX IF EXISTS idx_devices_tenant_id")
    op.execute("DROP TABLE IF EXISTS devices")

    op.execute("DROP INDEX IF EXISTS idx_waitlist_tracking_token")
    op.execute("ALTER TABLE waitlist DROP COLUMN IF EXISTS tracking_token")

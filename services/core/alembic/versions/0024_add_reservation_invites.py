"""Add reservation_invites table for guest companion invitations.

Revision ID: 0024_reservation_invites
Revises: 0023_payment_terminals
Create Date: 2026-04-14
"""

from __future__ import annotations

from alembic import op

revision = "0024_reservation_invites"
down_revision = "0023_payment_terminals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum-Type
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE invite_status AS ENUM ('pending', 'accepted', 'declined');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Tabelle
    op.execute("""
        CREATE TABLE IF NOT EXISTS reservation_invites (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
            reservation_id  UUID NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
            invite_token    VARCHAR(64) NOT NULL UNIQUE,
            status          invite_status NOT NULL DEFAULT 'pending',
            inviter_guest_profile_id UUID REFERENCES guest_profiles(id) ON DELETE SET NULL,
            inviter_name    VARCHAR(240) NOT NULL,
            guest_first_name VARCHAR(120),
            guest_last_name  VARCHAR(120),
            guest_allergen_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            accepted_at     TIMESTAMPTZ,
            declined_at     TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # Indizes einzeln
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reservation_invites_tenant_id ON reservation_invites(tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reservation_invites_reservation_id ON reservation_invites(reservation_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reservation_invites_invite_token ON reservation_invites(invite_token)"
    )

    # RLS
    op.execute("ALTER TABLE reservation_invites ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY reservation_invites_tenant_isolation
            ON reservation_invites
            USING (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)

    # Grants (nur wenn Rollen existieren, damit lokale Dev-DBs nicht fehlschlagen)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gastropilot_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON reservation_invites TO gastropilot_app;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gastropilot_admin') THEN
                GRANT ALL ON reservation_invites TO gastropilot_admin;
            END IF;
        END $$;
    """)

    # Updated-at Trigger
    op.execute("""
        CREATE OR REPLACE TRIGGER set_updated_at_reservation_invites
            BEFORE UPDATE ON reservation_invites
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at()
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reservation_invites CASCADE")
    op.execute("DROP TYPE IF EXISTS invite_status")

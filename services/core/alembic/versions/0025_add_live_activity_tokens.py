"""Add live_activity_tokens table for iOS Live Activity push tokens.

Revision ID: 0025_live_activity_tokens
Revises: 0024_reservation_invites
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op

revision = "0025_live_activity_tokens"
down_revision = "0024_reservation_invites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS live_activity_tokens (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
            order_id        UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            push_token      VARCHAR(256) NOT NULL,
            started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            ended_at        TIMESTAMPTZ,
            CONSTRAINT uq_lat_order_token UNIQUE (order_id, push_token)
        )
        """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_live_activity_tokens_tenant_id "
        "ON live_activity_tokens(tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_live_activity_tokens_order_id "
        "ON live_activity_tokens(order_id)"
    )
    # Hot-Path: nur aktive Live Activities holen (ended_at IS NULL).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_live_activity_tokens_active_order "
        "ON live_activity_tokens(order_id) WHERE ended_at IS NULL"
    )

    # RLS aktivieren (tenant-scoped).
    op.execute("ALTER TABLE live_activity_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY live_activity_tokens_tenant_isolation
            ON live_activity_tokens
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """)

    # Grants – nur, wenn Rollen existieren (lokale Dev-DBs nicht brechen).
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gastropilot_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON live_activity_tokens TO gastropilot_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gastropilot_admin') THEN
                GRANT ALL ON live_activity_tokens TO gastropilot_admin;
            END IF;
        END $$;
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS live_activity_tokens CASCADE")

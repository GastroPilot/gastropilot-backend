"""Add fiskaly_cash_point_closings table for DSFinV-K daily closings.

Revision ID: 0020_fiskaly_cash_point_closings
Revises: 0019_notifications_inbox
Create Date: 2026-04-14
"""

from __future__ import annotations

from alembic import op

revision = "0020_fiskaly_cash_point_closings"
down_revision = "0019_notifications_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS fiskaly_cash_point_closings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            closing_id UUID NOT NULL UNIQUE,
            business_date VARCHAR(10) NOT NULL,
            state VARCHAR(32) NOT NULL DEFAULT 'PENDING',
            cash_register_export_id VARCHAR(50),
            total_amount DOUBLE PRECISION,
            total_cash DOUBLE PRECISION,
            total_non_cash DOUBLE PRECISION,
            transaction_count INTEGER,
            is_training BOOLEAN NOT NULL DEFAULT FALSE,
            raw_request JSONB,
            raw_response JSONB,
            error TEXT,
            dsfinvk_export_id UUID,
            dsfinvk_export_state VARCHAR(32),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_fiskaly_cash_point_closings_tenant_id
            ON fiskaly_cash_point_closings (tenant_id)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_fiskaly_cash_point_closings_business_date
            ON fiskaly_cash_point_closings (tenant_id, business_date)
    """)

    op.execute("""
        ALTER TABLE fiskaly_cash_point_closings ENABLE ROW LEVEL SECURITY
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'fiskaly_cash_point_closings'
                  AND policyname = 'tenant_isolation_fiskaly_cash_point_closings'
            ) THEN
                CREATE POLICY tenant_isolation_fiskaly_cash_point_closings
                    ON fiskaly_cash_point_closings
                    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("""
        DROP POLICY IF EXISTS tenant_isolation_fiskaly_cash_point_closings
            ON fiskaly_cash_point_closings
    """)

    op.execute("DROP TABLE IF EXISTS fiskaly_cash_point_closings")

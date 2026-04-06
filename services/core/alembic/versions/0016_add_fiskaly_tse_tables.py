"""Add fiskaly KassenSichV TSE tables for TSS config and transaction signing.

Revision ID: 0016_fiskaly_tse_tables
Revises: 0015_order_item_kitchen_tickets
Create Date: 2026-04-06
"""

from __future__ import annotations

from alembic import op

revision = "0016_fiskaly_tse_tables"
down_revision = "0015_order_item_kitchen_tickets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fiskaly_tss_configs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            tss_id UUID NOT NULL,
            client_id UUID NOT NULL,
            client_serial_number VARCHAR(128) NOT NULL,
            tss_serial_number VARCHAR(256),
            admin_pin VARCHAR(64) NOT NULL,
            state VARCHAR(32) NOT NULL DEFAULT 'CREATED',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_fiskaly_tss_configs_tenant UNIQUE (tenant_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fiskaly_transactions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            tss_id UUID NOT NULL,
            tx_id UUID NOT NULL,
            tx_number BIGINT,
            tx_state VARCHAR(32),
            receipt_type VARCHAR(32),
            time_start BIGINT,
            time_end BIGINT,
            signature_value TEXT,
            signature_algorithm VARCHAR(64),
            signature_counter BIGINT,
            qr_code_data TEXT,
            tss_serial_number VARCHAR(256),
            client_serial_number VARCHAR(128),
            raw_response JSONB,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fiskaly_transactions_tenant_id "
        "ON fiskaly_transactions(tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fiskaly_transactions_order_id "
        "ON fiskaly_transactions(order_id)"
    )

    # RLS policies
    op.execute("ALTER TABLE fiskaly_tss_configs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE fiskaly_transactions ENABLE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY fiskaly_tss_configs_tenant_isolation ON fiskaly_tss_configs
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY fiskaly_transactions_tenant_isolation ON fiskaly_transactions
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS fiskaly_transactions_tenant_isolation ON fiskaly_transactions")
    op.execute("DROP POLICY IF EXISTS fiskaly_tss_configs_tenant_isolation ON fiskaly_tss_configs")
    op.execute("DROP TABLE IF EXISTS fiskaly_transactions")
    op.execute("DROP TABLE IF EXISTS fiskaly_tss_configs")

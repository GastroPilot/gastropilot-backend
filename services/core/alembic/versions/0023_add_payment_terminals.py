"""Add payment_terminals and terminal_payments tables.

Revision ID: 0023_payment_terminals
Revises: 0022_restaurant_business_fields
Create Date: 2026-04-14
"""

from __future__ import annotations

from alembic import op

revision = "0023_payment_terminals"
down_revision = "0022_restaurant_business_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS payment_terminals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            provider VARCHAR(32) NOT NULL,
            name VARCHAR(200) NOT NULL,
            provider_terminal_id VARCHAR(128),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            metadata JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payment_terminals_tenant_id "
        "ON payment_terminals (tenant_id)"
    )

    op.execute("ALTER TABLE payment_terminals ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY payment_terminals_tenant_isolation ON payment_terminals
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS terminal_payments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            tenant_id UUID NOT NULL,
            terminal_id UUID REFERENCES payment_terminals(id) ON DELETE SET NULL,
            provider VARCHAR(32) NOT NULL,
            amount DOUBLE PRECISION NOT NULL,
            currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            provider_data JSONB,
            error TEXT,
            initiated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_terminal_payments_tenant_id "
        "ON terminal_payments (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_terminal_payments_order_id "
        "ON terminal_payments (order_id)"
    )

    op.execute("ALTER TABLE terminal_payments ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY terminal_payments_tenant_isolation ON terminal_payments
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS terminal_payments_tenant_isolation ON terminal_payments")
    op.execute("DROP TABLE IF EXISTS terminal_payments")
    op.execute("DROP POLICY IF EXISTS payment_terminals_tenant_isolation ON payment_terminals")
    op.execute("DROP TABLE IF EXISTS payment_terminals")

"""Add missing models: blocks, table_configs, waitlist, messages, user_settings,
vouchers, upsell_packages, prepayments and junction tables.

Since init.sql creates these tables already, we use IF NOT EXISTS throughout.

Revision ID: 0003_missing_models
Revises: 0002_remove_license
Create Date: 2026-02-24
"""

from __future__ import annotations

from alembic import op

revision = "0003_missing_models"
down_revision = "0002_remove_license"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All tables are created by init.sql with IF NOT EXISTS.
    # This migration ensures they exist when init.sql was not run (e.g. fresh Alembic setup).

    op.execute("""
    CREATE TABLE IF NOT EXISTS blocks (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
        start_at TIMESTAMPTZ NOT NULL,
        end_at TIMESTAMPTZ NOT NULL,
        reason TEXT,
        created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_blocks_tenant_id ON blocks(tenant_id)")

    op.execute("""
    CREATE TABLE IF NOT EXISTS block_assignments (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        block_id UUID NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
        table_id UUID NOT NULL REFERENCES tables(id) ON DELETE CASCADE,
        tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(block_id, table_id)
    )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_block_assignments_tenant_id ON block_assignments(tenant_id)"
    )

    op.execute("""
    CREATE TABLE IF NOT EXISTS table_day_configs (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
        table_id UUID REFERENCES tables(id) ON DELETE CASCADE,
        date DATE NOT NULL,
        is_hidden BOOLEAN NOT NULL DEFAULT FALSE,
        is_temporary BOOLEAN NOT NULL DEFAULT FALSE,
        number VARCHAR(50),
        capacity INTEGER,
        shape VARCHAR(20),
        position_x FLOAT,
        position_y FLOAT,
        width FLOAT,
        height FLOAT,
        is_active BOOLEAN,
        color VARCHAR(16),
        join_group_id INTEGER,
        is_joinable BOOLEAN,
        rotation INTEGER,
        notes TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(tenant_id, table_id, date)
    )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_table_day_configs_tenant_id ON table_day_configs(tenant_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_table_day_configs_date ON table_day_configs(date)")

    op.execute("""
    CREATE TABLE IF NOT EXISTS reservation_tables (
        reservation_id UUID REFERENCES reservations(id) ON DELETE CASCADE,
        table_id UUID REFERENCES tables(id) ON DELETE RESTRICT,
        tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
        start_at TIMESTAMPTZ NOT NULL,
        end_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (reservation_id, table_id)
    )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_reservation_tables_tenant_id ON reservation_tables(tenant_id)"
    )

    op.execute("""
    CREATE TABLE IF NOT EXISTS reservation_table_day_configs (
        reservation_id UUID REFERENCES reservations(id) ON DELETE CASCADE,
        table_day_config_id UUID REFERENCES table_day_configs(id) ON DELETE CASCADE,
        tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
        start_at TIMESTAMPTZ NOT NULL,
        end_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (reservation_id, table_day_config_id)
    )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_reservation_table_day_configs_tenant_id ON reservation_table_day_configs(tenant_id)"
    )

    op.execute("""
    CREATE TABLE IF NOT EXISTS waitlist (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
        guest_id UUID REFERENCES guests(id) ON DELETE CASCADE,
        party_size INTEGER NOT NULL,
        desired_from TIMESTAMPTZ,
        desired_to TIMESTAMPTZ,
        status VARCHAR(24) NOT NULL DEFAULT 'waiting',
        priority INTEGER,
        notified_at TIMESTAMPTZ,
        confirmed_at TIMESTAMPTZ,
        notes TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_waitlist_tenant_id ON waitlist(tenant_id)")

    op.execute("""
    CREATE TABLE IF NOT EXISTS user_settings (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id UUID UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        settings JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS vouchers (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
        code VARCHAR(64) UNIQUE NOT NULL,
        name VARCHAR(240),
        description TEXT,
        type VARCHAR(32) NOT NULL DEFAULT 'fixed',
        value FLOAT NOT NULL,
        valid_from DATE,
        valid_until DATE,
        max_uses INTEGER,
        used_count INTEGER NOT NULL DEFAULT 0,
        min_order_value FLOAT,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_vouchers_tenant_id ON vouchers(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_vouchers_code ON vouchers(code)")

    op.execute("""
    CREATE TABLE IF NOT EXISTS voucher_usage (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        voucher_id UUID NOT NULL REFERENCES vouchers(id) ON DELETE CASCADE,
        reservation_id UUID REFERENCES reservations(id) ON DELETE SET NULL,
        tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
        used_by_email VARCHAR(255),
        discount_amount FLOAT NOT NULL,
        used_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_voucher_usage_tenant_id ON voucher_usage(tenant_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_voucher_usage_voucher_id ON voucher_usage(voucher_id)"
    )

    op.execute("""
    CREATE TABLE IF NOT EXISTS upsell_packages (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
        name VARCHAR(240) NOT NULL,
        description TEXT,
        price FLOAT NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        available_from_date DATE,
        available_until_date DATE,
        min_party_size INTEGER,
        max_party_size INTEGER,
        available_times JSONB,
        available_weekdays JSONB,
        image_url VARCHAR(512),
        display_order INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_upsell_packages_tenant_id ON upsell_packages(tenant_id)"
    )

    op.execute("""
    CREATE TABLE IF NOT EXISTS reservation_upsell_packages (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        reservation_id UUID NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
        upsell_package_id UUID NOT NULL REFERENCES upsell_packages(id) ON DELETE CASCADE,
        tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
        price_at_time FLOAT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(reservation_id, upsell_package_id)
    )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_reservation_upsell_packages_tenant_id ON reservation_upsell_packages(tenant_id)"
    )

    op.execute("""
    CREATE TABLE IF NOT EXISTS reservation_prepayments (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        reservation_id UUID NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
        tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
        amount FLOAT NOT NULL,
        currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
        payment_provider VARCHAR(32) NOT NULL,
        payment_id VARCHAR(128),
        transaction_id VARCHAR(128),
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        payment_data JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMPTZ
    )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_reservation_prepayments_tenant_id ON reservation_prepayments(tenant_id)"
    )

    op.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
        reservation_id UUID REFERENCES reservations(id) ON DELETE SET NULL,
        guest_id UUID REFERENCES guests(id) ON DELETE SET NULL,
        direction VARCHAR(32) NOT NULL,
        channel VARCHAR(32) NOT NULL,
        address VARCHAR(255) NOT NULL,
        body TEXT NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'queued',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_messages_tenant_id ON messages(tenant_id)")

    # RLS for new tables
    for table in [
        "blocks",
        "block_assignments",
        "table_day_configs",
        "reservation_tables",
        "reservation_table_day_configs",
        "waitlist",
        "vouchers",
        "voucher_usage",
        "upsell_packages",
        "reservation_upsell_packages",
        "reservation_prepayments",
        "messages",
        "audit_logs",
    ]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$ BEGIN
                CREATE POLICY tenant_isolation ON {table}
                    USING (tenant_id = current_tenant_id());
            EXCEPTION WHEN duplicate_object THEN NULL; END $$
        """)

    # order_items has no tenant_id column — policy via parent order
    op.execute("ALTER TABLE order_items ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DO $$ BEGIN
            CREATE POLICY tenant_isolation ON order_items
                USING (order_id IN (SELECT id FROM orders WHERE tenant_id = current_tenant_id()));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)


def downgrade() -> None:
    for table in [
        "messages",
        "reservation_prepayments",
        "reservation_upsell_packages",
        "upsell_packages",
        "voucher_usage",
        "vouchers",
        "user_settings",
        "waitlist",
        "reservation_table_day_configs",
        "reservation_tables",
        "table_day_configs",
        "block_assignments",
        "blocks",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

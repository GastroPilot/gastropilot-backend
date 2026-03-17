"""Initial schema – Microservices v2.0

Revision ID: 0001_initial
Revises:
Create Date: 2026-02-23

Hinweis: Diese Migration erwartet, dass init.sql und rls.sql bereits über
Docker-Entrypoint oder manuell ausgeführt wurden. Sie erstellt die
SQLAlchemy-spezifischen Constraints und Indizes on top.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Wenn init.sql bereits gelaufen ist, existiert restaurants bereits → skip
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'restaurants')"
        )
    )
    if result.scalar():
        return

    # Enums (idempotent, bereits in init.sql erstellt – hier als native Enum referenziert)
    user_role = postgresql.ENUM(
        "guest",
        "owner",
        "manager",
        "staff",
        "kitchen",
        "platform_admin",
        "platform_support",
        "platform_analyst",
        name="user_role",
        create_type=False,
    )
    auth_method = postgresql.ENUM("pin", "password", "nfc", name="auth_method", create_type=False)
    order_status = postgresql.ENUM(
        "pending",
        "confirmed",
        "sent_to_kitchen",
        "in_preparation",
        "ready",
        "served",
        "completed",
        "cancelled",
        name="order_status",
        create_type=False,
    )
    reservation_status = postgresql.ENUM(
        "pending",
        "confirmed",
        "seated",
        "completed",
        "cancelled",
        "no_show",
        name="reservation_status",
        create_type=False,
    )
    subscription_tier = postgresql.ENUM(
        "starter",
        "growth",
        "pro",
        "enterprise",
        name="subscription_tier",
        create_type=False,
    )

    # restaurants
    op.create_table(
        "restaurants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, nullable=True),
        sa.Column("address", sa.Text, nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("timezone", sa.String(50), server_default="Europe/Berlin"),
        sa.Column("currency", sa.String(3), server_default="EUR"),
        sa.Column("language", sa.String(10), server_default="de"),
        sa.Column("subscription_tier", subscription_tier, server_default="starter"),
        sa.Column("is_suspended", sa.Boolean, server_default="false"),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("settings", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # users
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("password_hash", sa.Text, nullable=True),
        sa.Column("pin_hash", sa.Text, nullable=True),
        sa.Column("operator_number", sa.String(20), nullable=True),
        sa.Column("nfc_tag_id", sa.String(100), nullable=True),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("auth_method", auth_method, server_default="pin"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index(
        "ix_users_email",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "ix_users_operator_number",
        "users",
        ["tenant_id", "operator_number"],
        unique=True,
        postgresql_where=sa.text("operator_number IS NOT NULL"),
    )

    # refresh_tokens
    op.create_table(
        "refresh_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        sa.Column("rotated_from_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    # areas
    op.create_table(
        "areas",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("sort_order", sa.Integer, server_default="0"),
    )

    # tables
    op.create_table(
        "tables",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "area_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("areas.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("capacity", sa.Integer, nullable=False),
        sa.Column("min_capacity", sa.Integer, server_default="1"),
        sa.Column("is_outdoor", sa.Boolean, server_default="false"),
        sa.Column("is_joinable", sa.Boolean, server_default="false"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("pos_x", sa.Float, server_default="0"),
        sa.Column("pos_y", sa.Float, server_default="0"),
        sa.Column("width", sa.Float, server_default="80"),
        sa.Column("height", sa.Float, server_default="80"),
    )
    op.create_index("ix_tables_tenant_id", "tables", ["tenant_id"])

    # menu_categories
    op.create_table(
        "menu_categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
    )

    # menu_items
    op.create_table(
        "menu_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("menu_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_available", sa.Boolean, server_default="true"),
        sa.Column("is_vegetarian", sa.Boolean, server_default="false"),
        sa.Column("is_vegan", sa.Boolean, server_default="false"),
        sa.Column("allergens", postgresql.ARRAY(sa.Text), server_default="{}"),
        sa.Column("ingredients", postgresql.JSONB, server_default="[]"),
        sa.Column("tags", postgresql.ARRAY(sa.Text), server_default="{}"),
        sa.Column("image_url", sa.Text, nullable=True),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_menu_items_tenant_id", "menu_items", ["tenant_id"])

    # guests
    op.create_table(
        "guests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # reservations
    op.create_table(
        "reservations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "guest_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("guests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "table_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tables.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("party_size", sa.Integer, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", reservation_status, server_default="pending"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("source", sa.String(50), server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_reservations_tenant_id", "reservations", ["tenant_id"])
    op.create_index("ix_reservations_starts_at", "reservations", ["starts_at"])

    # audit_logs
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entity_type", sa.String(100), nullable=True),
        sa.Column("entity_id", sa.String(100), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("details", postgresql.JSONB, nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    # platform_audit_logs
    op.create_table(
        "platform_audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("details", postgresql.JSONB, nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_platform_audit_logs_created_at", "platform_audit_logs", ["created_at"])

    # orders (in Orders-Service, aber als Reference hier für FK-Konsistenz)
    op.create_table(
        "orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "table_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tables.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("order_number", sa.String(20), nullable=False),
        sa.Column("status", order_status, server_default="pending"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_orders_tenant_id", "orders", ["tenant_id"])
    op.create_index("ix_orders_status", "orders", ["tenant_id", "status"])

    # order_items
    op.create_table(
        "order_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("menu_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("platform_audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("reservations")
    op.drop_table("guests")
    op.drop_table("menu_items")
    op.drop_table("menu_categories")
    op.drop_table("tables")
    op.drop_table("areas")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    op.drop_table("restaurants")

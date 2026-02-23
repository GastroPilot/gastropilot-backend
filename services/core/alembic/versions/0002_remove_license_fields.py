"""Remove license/subscription/payment fields from restaurants

Revision ID: 0002_remove_license
Revises: 0001_initial
Create Date: 2026-02-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_remove_license"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Spalten entfernen
    op.drop_column("restaurants", "subscription_tier")
    op.drop_column("restaurants", "is_suspended")
    op.drop_column("restaurants", "suspended_reason")
    op.drop_column("restaurants", "suspended_at")
    op.drop_column("restaurants", "payment_provider")
    op.drop_column("restaurants", "stripe_customer_id")
    op.drop_column("restaurants", "stripe_subscription_id")
    op.drop_column("restaurants", "sumup_merchant_code")
    op.drop_column("restaurants", "sumup_api_key")
    op.drop_column("restaurants", "sumup_default_reader_id")

    # Index der jetzt entfernten subscription_tier-Spalte löschen (falls vorhanden)
    op.execute("DROP INDEX IF EXISTS idx_restaurants_tier")

    # ENUMs löschen (nur wenn nicht mehr referenziert)
    op.execute("DROP TYPE IF EXISTS subscription_tier")
    op.execute("DROP TYPE IF EXISTS payment_provider")


def downgrade() -> None:
    # ENUMs wiederherstellen
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE subscription_tier AS ENUM ('free', 'starter', 'professional', 'enterprise');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE payment_provider AS ENUM ('stripe', 'sumup', 'both');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)

    # Spalten wiederherstellen
    op.add_column("restaurants", sa.Column("subscription_tier", sa.Text, server_default="starter"))
    op.add_column("restaurants", sa.Column("is_suspended", sa.Boolean, server_default="false"))
    op.add_column("restaurants", sa.Column("suspended_reason", sa.Text, nullable=True))
    op.add_column("restaurants", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("restaurants", sa.Column("payment_provider", sa.Text, server_default="sumup"))
    op.add_column("restaurants", sa.Column("stripe_customer_id", sa.String(128), nullable=True))
    op.add_column("restaurants", sa.Column("stripe_subscription_id", sa.String(128), nullable=True))
    op.add_column("restaurants", sa.Column("sumup_merchant_code", sa.String(32), nullable=True))
    op.add_column("restaurants", sa.Column("sumup_api_key", sa.String(255), nullable=True))
    op.add_column("restaurants", sa.Column("sumup_default_reader_id", sa.String(64), nullable=True))

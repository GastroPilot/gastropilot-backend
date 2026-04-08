"""Add per-tenant fiskaly organization credentials to TSS config.

Revision ID: 0018_fiskaly_org_credentials
Revises: 0017_fiskaly_receipt_fields
Create Date: 2026-04-06
"""

from __future__ import annotations

from alembic import op

revision = "0018_fiskaly_org_credentials"
down_revision = "0017_fiskaly_receipt_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE fiskaly_tss_configs ADD COLUMN IF NOT EXISTS fiskaly_org_id UUID"
    )
    op.execute(
        "ALTER TABLE fiskaly_tss_configs "
        "ADD COLUMN IF NOT EXISTS fiskaly_api_key VARCHAR(256)"
    )
    op.execute(
        "ALTER TABLE fiskaly_tss_configs "
        "ADD COLUMN IF NOT EXISTS fiskaly_api_secret VARCHAR(256)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE fiskaly_tss_configs DROP COLUMN IF EXISTS fiskaly_api_secret")
    op.execute("ALTER TABLE fiskaly_tss_configs DROP COLUMN IF EXISTS fiskaly_api_key")
    op.execute("ALTER TABLE fiskaly_tss_configs DROP COLUMN IF EXISTS fiskaly_org_id")

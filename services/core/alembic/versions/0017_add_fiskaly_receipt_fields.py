"""Add receipt fields to fiskaly_transactions for eReceipt integration.

Revision ID: 0017_fiskaly_receipt_fields
Revises: 0016_fiskaly_tse_tables
Create Date: 2026-04-06
"""

from __future__ import annotations

from alembic import op

revision = "0017_fiskaly_receipt_fields"
down_revision = "0016_fiskaly_tse_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE fiskaly_transactions "
        "ADD COLUMN IF NOT EXISTS receipt_id VARCHAR(128)"
    )
    op.execute(
        "ALTER TABLE fiskaly_transactions "
        "ADD COLUMN IF NOT EXISTS receipt_public_url TEXT"
    )
    op.execute(
        "ALTER TABLE fiskaly_transactions "
        "ADD COLUMN IF NOT EXISTS receipt_pdf_url TEXT"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE fiskaly_transactions DROP COLUMN IF EXISTS receipt_pdf_url")
    op.execute("ALTER TABLE fiskaly_transactions DROP COLUMN IF EXISTS receipt_public_url")
    op.execute("ALTER TABLE fiskaly_transactions DROP COLUMN IF EXISTS receipt_id")

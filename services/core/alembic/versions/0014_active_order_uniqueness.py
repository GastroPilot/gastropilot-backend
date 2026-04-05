"""Compatibility bridge revision for environments stamped with 0014_active_order_uniqueness.

Revision ID: 0014_active_order_uniqueness
Revises: 0013_order_status_timestamps
Create Date: 2026-04-05

This migration intentionally contains no schema changes. Some environments
already reference this revision in `alembic_version`, but the file was missing
from the repository history after merges/rebases.
"""

from __future__ import annotations

from alembic import op

revision = "0014_active_order_uniqueness"
down_revision = "0013_order_status_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op compatibility revision.
    pass


def downgrade() -> None:
    # No-op compatibility revision.
    pass

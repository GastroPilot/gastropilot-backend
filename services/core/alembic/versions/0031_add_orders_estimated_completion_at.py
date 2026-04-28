"""Add orders.estimated_completion_at column.

Persists the order's expected ready time so the guest-side detail
endpoint, KDS and any future surfaces can read a single source of
truth instead of recomputing a heuristic on every request.

Initial value is ``NULL`` for all existing rows; the field is filled
by ``apply_order_status_timestamps`` when an order transitions into
``sent_to_kitchen``. AI-Service will later be able to overwrite it
asynchronously without an API change.

Issue: GastroPilot/GastroPilot#40 (BE-4).

Chain note
----------
This migration chains off ``0030_order_item_deal_meta`` (voucher /
menu-deal feature branch). The live-activity head ``0025_live_activity_tokens``
remains as a separate branch — needs an ``alembic merge`` once both
deployments line up. Tracked as a separate ops task.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0031_orders_eta_column"
down_revision = "0030_order_item_deal_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "estimated_completion_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "estimated_completion_at")

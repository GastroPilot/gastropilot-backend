"""Merge parallel migration heads back to a single head.

After ``feat/voucher-discount`` and the live-activity-feature branch
both merged into main, alembic saw two parallel heads:

- ``0025_live_activity_tokens`` (live-activity foundation, #35)
- ``0031_orders_eta_column``   (BE-4 from #40, chained through voucher's
                                 0027-0030)

``alembic upgrade head`` refuses to run with multiple heads. This is a
pure topological merge: no DDL, just a join node so future migrations
can chain off a single revision again.

Issue: GastroPilot/GastroPilot#51.
"""

from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "0032_merge_la_eta_heads"
down_revision = ("0025_live_activity_tokens", "0031_orders_eta_column")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Empty merge — no DDL changes."""


def downgrade() -> None:
    """Empty merge — no DDL changes."""

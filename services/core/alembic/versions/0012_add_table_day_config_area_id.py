"""Add area_id to table_day_configs for area-scoped temporary tables.

Revision ID: 0012_table_day_config_area
Revises: 0011_orders_table_ids
Create Date: 2026-03-23
"""

from __future__ import annotations

from alembic import op

revision = "0012_table_day_config_area"
down_revision = "0011_orders_table_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE table_day_configs ADD COLUMN IF NOT EXISTS area_id UUID")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_table_day_configs_area_id_areas'
            ) THEN
                ALTER TABLE table_day_configs
                ADD CONSTRAINT fk_table_day_configs_area_id_areas
                FOREIGN KEY (area_id) REFERENCES areas(id) ON DELETE SET NULL;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_table_day_configs_area_id ON table_day_configs(area_id)"
    )

    # Backfill non-temporary configs from the linked permanent table.
    op.execute(
        """
        UPDATE table_day_configs AS tdc
        SET area_id = t.area_id
        FROM tables AS t
        WHERE tdc.table_id = t.id
          AND tdc.area_id IS NULL
        """
    )

    # Best effort backfill for temporary grouped tables.
    op.execute(
        """
        UPDATE table_day_configs AS tmp
        SET area_id = src.area_id
        FROM (
            SELECT DISTINCT ON (tenant_id, date, join_group_id)
                tenant_id,
                date,
                join_group_id,
                area_id
            FROM table_day_configs
            WHERE area_id IS NOT NULL
              AND join_group_id IS NOT NULL
            ORDER BY tenant_id, date, join_group_id, area_id::text
        ) AS src
        WHERE tmp.area_id IS NULL
          AND tmp.is_temporary IS TRUE
          AND tmp.join_group_id IS NOT NULL
          AND tmp.tenant_id = src.tenant_id
          AND tmp.date = src.date
          AND tmp.join_group_id = src.join_group_id
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_table_day_configs_area_id")
    op.execute(
        """
        ALTER TABLE table_day_configs
        DROP CONSTRAINT IF EXISTS fk_table_day_configs_area_id_areas
        """
    )
    op.execute("ALTER TABLE table_day_configs DROP COLUMN IF EXISTS area_id")

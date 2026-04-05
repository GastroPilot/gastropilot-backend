"""Add category_type to menu categories for domain-level food/drink semantics.

Revision ID: 0014_menu_category_type
Revises: 0014_active_order_uniqueness
Create Date: 2026-04-05
"""

from __future__ import annotations

from alembic import op

revision = "0014_menu_category_type"
down_revision = "0014_active_order_uniqueness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE menu_categories "
        "ADD COLUMN IF NOT EXISTS category_type VARCHAR(16) DEFAULT 'food'"
    )

    op.execute(
        "UPDATE menu_categories "
        "SET category_type = 'food' "
        "WHERE category_type IS NULL"
    )

    # Best-effort backfill for likely drink categories based on existing names.
    op.execute(
        """
        WITH normalized AS (
            SELECT
                id,
                lower(
                    replace(
                        replace(
                            replace(
                                replace(
                                    replace(
                                        replace(coalesce(name, ''), 'Ä', 'ae'),
                                        'Ö',
                                        'oe'
                                    ),
                                    'Ü',
                                    'ue'
                                ),
                                'ä',
                                'ae'
                            ),
                            'ö',
                            'oe'
                        ),
                        'ü',
                        'ue'
                    )
                ) AS name_normalized
            FROM menu_categories
        )
        UPDATE menu_categories AS c
        SET category_type = 'drink'
        FROM normalized AS n
        WHERE c.id = n.id
          AND (
            n.name_normalized LIKE '%getraenk%'
            OR n.name_normalized LIKE '%getrank%'
            OR n.name_normalized LIKE '%drink%'
            OR n.name_normalized LIKE '%beverage%'
            OR n.name_normalized LIKE '%cocktail%'
            OR n.name_normalized LIKE '%bier%'
            OR n.name_normalized LIKE '%wein%'
            OR n.name_normalized LIKE '%saft%'
            OR n.name_normalized LIKE '%kaffee%'
            OR n.name_normalized LIKE '%tee%'
            OR n.name_normalized LIKE '%wasser%'
            OR n.name_normalized LIKE '%limonade%'
          )
        """
    )

    op.execute(
        "ALTER TABLE menu_categories "
        "ALTER COLUMN category_type SET DEFAULT 'food'"
    )
    op.execute(
        "ALTER TABLE menu_categories "
        "ALTER COLUMN category_type SET NOT NULL"
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_menu_categories_category_type'
            ) THEN
                ALTER TABLE menu_categories
                ADD CONSTRAINT ck_menu_categories_category_type
                CHECK (category_type IN ('food', 'drink'));
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE menu_categories "
        "DROP CONSTRAINT IF EXISTS ck_menu_categories_category_type"
    )
    op.execute("ALTER TABLE menu_categories DROP COLUMN IF EXISTS category_type")

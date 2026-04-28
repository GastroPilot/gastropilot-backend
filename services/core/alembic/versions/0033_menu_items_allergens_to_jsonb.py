"""Migrate menu_items.allergens from ARRAY(Text) to JSONB.

Schema-Drift-Fix: ``0001_initial_schema`` legt ``menu_items.allergens`` als
``ARRAY(Text)`` an, während sowohl das SQLAlchemy-Modell
(``app/models/menu.py``) als auch das ``install/sql/init.sql``-Bootstrap-Skript
``JSONB`` deklarieren. Damit driften frisch via Alembic gebootete Datenbanken
gegenüber Prod-Installern auseinander.

Diese Migration:

1. prüft den aktuellen Spaltentyp und überspringt sich, falls bereits ``JSONB``
   vorliegt (idempotent — wichtig, da neue Installer die Tabelle bereits mit
   ``JSONB`` initialisieren);
2. konvertiert bestehende ``text[]``-Werte verlustfrei via
   ``USING to_jsonb(allergens)`` nach ``JSONB``;
3. bietet einen Downgrade-Pfad zurück nach ``ARRAY(Text)``, der JSON-Arrays in
   ``text[]`` zurückprojiziert (Werte, die keine Top-Level-Strings sind, werden
   beim Downgrade nach ``::text`` gecastet).

Issue: GastroPilot/GastroPilot#27.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0033_menu_items_allergens_to_jsonb"
down_revision = "0032_merge_la_eta_heads"
branch_labels = None
depends_on = None


def _current_allergens_udt(connection) -> str | None:
    """Return the lower-case ``udt_name`` of ``menu_items.allergens`` or None."""
    row = connection.exec_driver_sql(
        "SELECT udt_name FROM information_schema.columns "
        "WHERE table_name = 'menu_items' AND column_name = 'allergens'"
    ).first()
    return row[0].lower() if row and row[0] else None


def upgrade() -> None:
    bind = op.get_bind()
    udt = _current_allergens_udt(bind)

    if udt is None:
        # Spalte existiert nicht — nichts zu tun.
        return

    if udt == "jsonb":
        # Bereits JSONB (Installer-Bootstrap oder erneuter Run) → no-op.
        return

    # ARRAY-Typen erscheinen in pg_catalog mit führendem Underscore
    # (z. B. ``_text`` für ``text[]``). Zur Sicherheit deckt der Cast auch
    # andere Array-Varianten ab.
    op.execute(
        "ALTER TABLE menu_items "
        "ALTER COLUMN allergens TYPE JSONB "
        "USING to_jsonb(COALESCE(allergens, ARRAY[]::text[])), "
        "ALTER COLUMN allergens SET DEFAULT '[]'::jsonb"
    )

    # Existierende NULL-Werte normalisieren, damit das Modell-Default
    # (``default=list``) auch in der DB konsistent ist.
    op.execute("UPDATE menu_items SET allergens = '[]'::jsonb WHERE allergens IS NULL")


def downgrade() -> None:
    bind = op.get_bind()
    udt = _current_allergens_udt(bind)

    if udt is None or udt != "jsonb":
        # Nichts zu tun, wenn die Spalte nicht (mehr) JSONB ist.
        return

    # JSONB-Arrays nach text[] zurückprojizieren. Für Skalare/Objekte würde
    # ``jsonb_array_elements_text`` fehlschlagen — wir gehen daher den sicheren
    # Weg über ``jsonb_array_elements`` mit ``::text``-Cast und stripen
    # JSON-Quotes für reine String-Elemente.
    op.execute(
        "ALTER TABLE menu_items "
        "ALTER COLUMN allergens TYPE TEXT[] USING ("
        "  CASE "
        "    WHEN allergens IS NULL THEN ARRAY[]::text[] "
        "    WHEN jsonb_typeof(allergens) = 'array' THEN ("
        "      SELECT COALESCE(array_agg(elem), ARRAY[]::text[]) "
        "      FROM ("
        "        SELECT CASE "
        "          WHEN jsonb_typeof(value) = 'string' THEN value #>> '{}' "
        "          ELSE value::text "
        "        END AS elem "
        "        FROM jsonb_array_elements(allergens) AS value "
        "      ) AS elements "
        "    ) "
        "    ELSE ARRAY[]::text[] "
        "  END"
        "), "
        "ALTER COLUMN allergens SET DEFAULT '{}'::text[]"
    )

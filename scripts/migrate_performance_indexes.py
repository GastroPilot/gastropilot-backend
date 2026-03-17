#!/usr/bin/env python3
"""
Migration script to add performance indexes.

Usage:
    cd gastropilot/backend
    python -m scripts.migrate_performance_indexes

This script adds indexes to improve query performance for:
- Reservations (date filtering, status filtering)
- Orders (status, table, date)
- Tables (area, active status)
- Blocks and Block Assignments
- Audit Logs
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.database.instance import db

# Index definitions - compatible with both SQLite and PostgreSQL
INDEXES = [
    # ============================================
    # RESERVATIONS
    # ============================================
    {
        "name": "idx_reservations_restaurant_start_at",
        "table": "reservations",
        "columns": "restaurant_id, start_at",
    },
    {
        "name": "idx_reservations_restaurant_status",
        "table": "reservations",
        "columns": "restaurant_id, status",
    },
    {
        "name": "idx_reservations_dashboard",
        "table": "reservations",
        "columns": "restaurant_id, start_at, status",
    },
    {
        "name": "idx_reservations_table_start",
        "table": "reservations",
        "columns": "table_id, start_at",
        "where": "table_id IS NOT NULL",
    },
    # ============================================
    # ORDERS
    # ============================================
    {
        "name": "idx_orders_restaurant_status",
        "table": "orders",
        "columns": "restaurant_id, status",
    },
    {
        "name": "idx_orders_table_status",
        "table": "orders",
        "columns": "table_id, status",
        "where": "table_id IS NOT NULL",
    },
    {
        "name": "idx_orders_restaurant_opened",
        "table": "orders",
        "columns": "restaurant_id, opened_at",
    },
    {
        "name": "idx_orders_paid",
        "table": "orders",
        "columns": "restaurant_id, paid_at",
        "where": "status = 'paid'",
    },
    # ============================================
    # ORDER ITEMS
    # ============================================
    {
        "name": "idx_order_items_order_status",
        "table": "order_items",
        "columns": "order_id, status",
    },
    # ============================================
    # TABLES
    # ============================================
    {
        "name": "idx_tables_restaurant_active",
        "table": "tables",
        "columns": "restaurant_id, is_active",
    },
    {
        "name": "idx_tables_area",
        "table": "tables",
        "columns": "area_id",
        "where": "area_id IS NOT NULL",
    },
    # ============================================
    # TABLE_DAY_CONFIGS
    # ============================================
    {
        "name": "idx_table_day_configs_lookup",
        "table": "table_day_configs",
        "columns": "restaurant_id, date, table_id",
    },
    {
        "name": "idx_table_day_configs_temp",
        "table": "table_day_configs",
        "columns": "restaurant_id, date",
        "where": "is_temporary = true",
    },
    # ============================================
    # BLOCKS
    # ============================================
    {
        "name": "idx_blocks_restaurant_time",
        "table": "blocks",
        "columns": "restaurant_id, start_at, end_at",
    },
    # ============================================
    # BLOCK_ASSIGNMENTS
    # ============================================
    {
        "name": "idx_block_assignments_table",
        "table": "block_assignments",
        "columns": "table_id, block_id",
    },
    # ============================================
    # AUDIT_LOGS
    # ============================================
    {
        "name": "idx_audit_logs_restaurant_time",
        "table": "audit_logs",
        "columns": "restaurant_id, created_at_utc DESC",
    },
    {
        "name": "idx_audit_logs_entity",
        "table": "audit_logs",
        "columns": "entity_type, entity_id",
    },
    # ============================================
    # REFRESH_TOKENS
    # ============================================
    {
        "name": "idx_refresh_tokens_user_expires",
        "table": "refresh_tokens",
        "columns": "user_id, expires_at",
        "where": "revoked_at IS NULL",
    },
]


async def check_index_exists(conn, index_name: str, db_type: str) -> bool:
    """Check if an index already exists."""
    if db_type == "sqlite":
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND name=:name"),
            {"name": index_name},
        )
    else:  # PostgreSQL
        result = await conn.execute(
            text("SELECT indexname FROM pg_indexes WHERE indexname = :name"), {"name": index_name}
        )
    return result.fetchone() is not None


async def check_table_exists(conn, table_name: str, db_type: str) -> bool:
    """Check if a table exists."""
    if db_type == "sqlite":
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
            {"name": table_name},
        )
    else:  # PostgreSQL
        result = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE tablename = :name"), {"name": table_name}
        )
    return result.fetchone() is not None


async def create_index(conn, index_def: dict, db_type: str) -> tuple[bool, str]:
    """Create an index if it doesn't exist."""
    name = index_def["name"]
    table = index_def["table"]
    columns = index_def["columns"]
    where = index_def.get("where")

    # Check if table exists
    if not await check_table_exists(conn, table, db_type):
        return False, f"Tabelle '{table}' existiert nicht"

    # Check if index already exists
    if await check_index_exists(conn, name, db_type):
        return False, "Index existiert bereits"

    # Build CREATE INDEX statement
    sql = f"CREATE INDEX {name} ON {table}({columns})"
    if where:
        sql += f" WHERE {where}"

    try:
        await conn.execute(text(sql))
        return True, "Erstellt"
    except Exception as e:
        return False, str(e)


async def run_migration():
    """Run the performance indexes migration."""
    from app.settings import DB_TYPE

    print("=" * 60)
    print("Performance-Indizes Migration")
    print("=" * 60)
    print(f"Datenbank-Typ: {DB_TYPE}")
    print()

    created = 0
    skipped = 0
    errors = 0

    async with db.engine.begin() as conn:
        for index_def in INDEXES:
            name = index_def["name"]
            table = index_def["table"]

            success, message = await create_index(conn, index_def, DB_TYPE)

            if success:
                print(f"✅ {name} ({table}): {message}")
                created += 1
            elif "existiert bereits" in message or "existiert nicht" in message:
                print(f"⏭️  {name} ({table}): {message}")
                skipped += 1
            else:
                print(f"❌ {name} ({table}): {message}")
                errors += 1

    print()
    print("=" * 60)
    print("Zusammenfassung:")
    print(f"  Erstellt: {created}")
    print(f"  Übersprungen: {skipped}")
    print(f"  Fehler: {errors}")
    print("=" * 60)

    return errors == 0


if __name__ == "__main__":
    success = asyncio.run(run_migration())
    sys.exit(0 if success else 1)

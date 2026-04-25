#!/usr/bin/env python3
"""
Migrate data from legacy monolith (Integer IDs, restaurant_id) to
microservices schema (UUID IDs, tenant_id).

Usage:
    python migrate_legacy_data.py --legacy-db <LEGACY_URL> --target-db <TARGET_URL>
    python migrate_legacy_data.py --legacy-db <LEGACY_URL> --target-db <TARGET_URL> --dry-run
    python migrate_legacy_data.py --legacy-db <LEGACY_URL> --target-db <TARGET_URL> --verify-only
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import UTC, datetime

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Role mapping: legacy German roles -> new English roles
ROLE_MAP = {
    "platform_admin": "platform_admin",
    "servecta": "platform_support",
    "restaurantinhaber": "owner",
    "schichtleiter": "manager",
    "mitarbeiter": "staff",
}


class MigrationContext:
    def __init__(self, legacy_pool: asyncpg.Pool, target_pool: asyncpg.Pool, dry_run: bool = False):
        self.legacy = legacy_pool
        self.target = target_pool
        self.dry_run = dry_run
        # id_map[table_name][old_int_id] = new_uuid
        self.id_map: dict[str, dict[int, uuid.UUID]] = {}
        self.counts: dict[str, int] = {}

    def map_id(self, table: str, old_id: int) -> uuid.UUID:
        if table not in self.id_map:
            self.id_map[table] = {}
        if old_id not in self.id_map[table]:
            self.id_map[table][old_id] = uuid.uuid4()
        return self.id_map[table][old_id]

    def get_mapped_id(self, table: str, old_id: int | None) -> uuid.UUID | None:
        if old_id is None:
            return None
        return self.id_map.get(table, {}).get(old_id)

    async def execute(self, query: str, *args):
        if self.dry_run:
            logger.debug("DRY-RUN: %s", query[:120])
            return
        await self.target.execute(query, *args)

    async def executemany(self, query: str, args_list: list):
        if self.dry_run:
            logger.debug("DRY-RUN: %s (%d rows)", query[:80], len(args_list))
            return
        await self.target.executemany(query, args_list)


# ---------------------------------------------------------------------------
# Step 1: Restaurants -> Tenants
# ---------------------------------------------------------------------------
async def migrate_restaurants(ctx: MigrationContext) -> None:
    rows = await ctx.legacy.fetch("SELECT * FROM restaurants ORDER BY id")
    logger.info("Migrating %d restaurants...", len(rows))

    for row in rows:
        new_id = ctx.map_id("restaurants", row["id"])
        await ctx.execute(
            """INSERT INTO restaurants (
                id, name, slug, address, phone, email, description,
                public_booking_enabled, booking_lead_time_hours,
                booking_max_party_size, booking_default_duration,
                opening_hours, sumup_enabled, sumup_merchant_code,
                sumup_api_key, sumup_default_reader_id,
                created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
            ON CONFLICT (id) DO NOTHING""",
            new_id,
            row["name"],
            row["slug"],
            row["address"],
            row["phone"],
            row["email"],
            row["description"],
            row.get("public_booking_enabled", False),
            row.get("booking_lead_time_hours", 2),
            row.get("booking_max_party_size", 12),
            row.get("booking_default_duration", 120),
            row.get("opening_hours"),
            row.get("sumup_enabled", False),
            row.get("sumup_merchant_code"),
            row.get("sumup_api_key"),
            row.get("sumup_default_reader_id"),
            row.get("created_at_utc", datetime.now(UTC)),
            row.get("updated_at_utc", datetime.now(UTC)),
        )

    ctx.counts["restaurants"] = len(rows)


# ---------------------------------------------------------------------------
# Step 2: Users
# ---------------------------------------------------------------------------
async def migrate_users(ctx: MigrationContext) -> None:
    rows = await ctx.legacy.fetch("SELECT * FROM users ORDER BY id")
    logger.info("Migrating %d users...", len(rows))

    for row in rows:
        new_id = ctx.map_id("users", row["id"])
        old_role = (row.get("role") or "mitarbeiter").lower()
        new_role = ROLE_MAP.get(old_role, "staff")

        await ctx.execute(
            """INSERT INTO users (
                id, operator_number, pin_hash, nfc_tag_id, email, password_hash,
                first_name, last_name, role, auth_method, is_active,
                created_at, updated_at, last_login_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            ON CONFLICT (id) DO NOTHING""",
            new_id,
            row.get("operator_number"),
            row.get("pin_hash"),
            row.get("nfc_tag_id"),
            row.get("email"),
            row.get("password_hash"),
            row.get("first_name"),
            row.get("last_name"),
            new_role,
            "email",
            row.get("is_active", True),
            row.get("created_at_utc", datetime.now(UTC)),
            row.get("updated_at_utc", datetime.now(UTC)),
            row.get("last_login_at_utc"),
        )

    ctx.counts["users"] = len(rows)


# ---------------------------------------------------------------------------
# Step 3: Areas
# ---------------------------------------------------------------------------
async def migrate_areas(ctx: MigrationContext) -> None:
    rows = await ctx.legacy.fetch("SELECT * FROM areas ORDER BY id")
    logger.info("Migrating %d areas...", len(rows))

    for row in rows:
        new_id = ctx.map_id("areas", row["id"])
        tenant_id = ctx.get_mapped_id("restaurants", row["restaurant_id"])
        if not tenant_id:
            continue
        await ctx.execute(
            """INSERT INTO areas (id, tenant_id, name)
            VALUES ($1,$2,$3) ON CONFLICT (id) DO NOTHING""",
            new_id,
            tenant_id,
            row["name"],
        )
    ctx.counts["areas"] = len(rows)


# ---------------------------------------------------------------------------
# Step 4: Tables
# ---------------------------------------------------------------------------
async def migrate_tables(ctx: MigrationContext) -> None:
    rows = await ctx.legacy.fetch("SELECT * FROM tables ORDER BY id")
    logger.info("Migrating %d tables...", len(rows))

    for row in rows:
        new_id = ctx.map_id("tables", row["id"])
        tenant_id = ctx.get_mapped_id("restaurants", row["restaurant_id"])
        area_id = ctx.get_mapped_id("areas", row.get("area_id"))
        if not tenant_id:
            continue
        await ctx.execute(
            """INSERT INTO tables (
                id, tenant_id, area_id, number, capacity, shape,
                position_x, position_y, width, height, is_active,
                notes, is_joinable, join_group_id, is_outdoor, rotation,
                created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
            ON CONFLICT (id) DO NOTHING""",
            new_id,
            tenant_id,
            area_id,
            row.get("number"),
            row.get("capacity"),
            row.get("shape", "rectangle"),
            row.get("position_x"),
            row.get("position_y"),
            row.get("width", 120.0),
            row.get("height", 120.0),
            row.get("is_active", True),
            row.get("notes"),
            row.get("is_joinable", False),
            row.get("join_group_id"),
            row.get("is_outdoor", False),
            row.get("rotation"),
            row.get("created_at_utc", datetime.now(UTC)),
            row.get("updated_at_utc", datetime.now(UTC)),
        )
    ctx.counts["tables"] = len(rows)


# ---------------------------------------------------------------------------
# Step 5: Obstacles
# ---------------------------------------------------------------------------
async def migrate_obstacles(ctx: MigrationContext) -> None:
    rows = await ctx.legacy.fetch("SELECT * FROM obstacles ORDER BY id")
    logger.info("Migrating %d obstacles...", len(rows))

    for row in rows:
        new_id = ctx.map_id("obstacles", row["id"])
        tenant_id = ctx.get_mapped_id("restaurants", row["restaurant_id"])
        area_id = ctx.get_mapped_id("areas", row.get("area_id"))
        if not tenant_id:
            continue
        await ctx.execute(
            """INSERT INTO obstacles (
                id, tenant_id, area_id, type, name, x, y, width, height,
                rotation, blocking, color, notes
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            ON CONFLICT (id) DO NOTHING""",
            new_id,
            tenant_id,
            area_id,
            row.get("type"),
            row.get("name"),
            row.get("x"),
            row.get("y"),
            row.get("width"),
            row.get("height"),
            row.get("rotation"),
            row.get("blocking", True),
            row.get("color"),
            row.get("notes"),
        )
    ctx.counts["obstacles"] = len(rows)


# ---------------------------------------------------------------------------
# Step 6: Guests
# ---------------------------------------------------------------------------
async def migrate_guests(ctx: MigrationContext) -> None:
    rows = await ctx.legacy.fetch("SELECT * FROM guests ORDER BY id")
    logger.info("Migrating %d guests...", len(rows))

    for row in rows:
        new_id = ctx.map_id("guests", row["id"])
        tenant_id = ctx.get_mapped_id("restaurants", row["restaurant_id"])
        if not tenant_id:
            continue
        await ctx.execute(
            """INSERT INTO guests (
                id, tenant_id, first_name, last_name, email, phone,
                language, birthday, company, type, notes,
                created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            ON CONFLICT (id) DO NOTHING""",
            new_id,
            tenant_id,
            row.get("first_name"),
            row.get("last_name"),
            row.get("email"),
            row.get("phone"),
            row.get("language"),
            row.get("birthday"),
            row.get("company"),
            row.get("type"),
            row.get("notes"),
            row.get("created_at_utc", datetime.now(UTC)),
            row.get("updated_at_utc", datetime.now(UTC)),
        )
    ctx.counts["guests"] = len(rows)


# ---------------------------------------------------------------------------
# Step 7: Menu Categories + Items
# ---------------------------------------------------------------------------
async def migrate_menu(ctx: MigrationContext) -> None:
    cats = await ctx.legacy.fetch("SELECT * FROM menu_categories ORDER BY id")
    logger.info("Migrating %d menu categories...", len(cats))
    for row in cats:
        new_id = ctx.map_id("menu_categories", row["id"])
        tenant_id = ctx.get_mapped_id("restaurants", row["restaurant_id"])
        if not tenant_id:
            continue
        await ctx.execute(
            """INSERT INTO menu_categories (
                id, tenant_id, name, description, sort_order, is_active,
                created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (id) DO NOTHING""",
            new_id,
            tenant_id,
            row["name"],
            row.get("description"),
            row.get("sort_order", 0),
            row.get("is_active", True),
            row.get("created_at_utc", datetime.now(UTC)),
            row.get("updated_at_utc", datetime.now(UTC)),
        )
    ctx.counts["menu_categories"] = len(cats)

    items = await ctx.legacy.fetch("SELECT * FROM menu_items ORDER BY id")
    logger.info("Migrating %d menu items...", len(items))
    for row in items:
        new_id = ctx.map_id("menu_items", row["id"])
        tenant_id = ctx.get_mapped_id("restaurants", row["restaurant_id"])
        cat_id = ctx.get_mapped_id("menu_categories", row.get("category_id"))
        if not tenant_id:
            continue
        await ctx.execute(
            """INSERT INTO menu_items (
                id, tenant_id, category_id, name, description, price,
                tax_rate, is_available, sort_order, allergens, modifiers,
                created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            ON CONFLICT (id) DO NOTHING""",
            new_id,
            tenant_id,
            cat_id,
            row["name"],
            row.get("description"),
            row.get("price"),
            row.get("tax_rate", 0.19),
            row.get("is_available", True),
            row.get("sort_order", 0),
            row.get("allergens"),
            row.get("modifiers"),
            row.get("created_at_utc", datetime.now(UTC)),
            row.get("updated_at_utc", datetime.now(UTC)),
        )
    ctx.counts["menu_items"] = len(items)


# ---------------------------------------------------------------------------
# Step 8: Blocks + Assignments
# ---------------------------------------------------------------------------
async def migrate_blocks(ctx: MigrationContext) -> None:
    rows = await ctx.legacy.fetch("SELECT * FROM blocks ORDER BY id")
    logger.info("Migrating %d blocks...", len(rows))
    for row in rows:
        new_id = ctx.map_id("blocks", row["id"])
        tenant_id = ctx.get_mapped_id("restaurants", row["restaurant_id"])
        created_by = ctx.get_mapped_id("users", row.get("created_by_user_id"))
        if not tenant_id:
            continue
        await ctx.execute(
            """INSERT INTO blocks (id, tenant_id, start_at, end_at, reason, created_by_user_id)
            VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (id) DO NOTHING""",
            new_id,
            tenant_id,
            row["start_at"],
            row["end_at"],
            row.get("reason"),
            created_by,
        )
    ctx.counts["blocks"] = len(rows)

    assignments = await ctx.legacy.fetch("SELECT * FROM block_assignments ORDER BY id")
    logger.info("Migrating %d block assignments...", len(assignments))
    for row in assignments:
        new_id = ctx.map_id("block_assignments", row["id"])
        block_id = ctx.get_mapped_id("blocks", row["block_id"])
        table_id = ctx.get_mapped_id("tables", row["table_id"])
        if not block_id or not table_id:
            continue
        await ctx.execute(
            """INSERT INTO block_assignments (id, block_id, table_id, created_at)
            VALUES ($1,$2,$3,$4) ON CONFLICT (id) DO NOTHING""",
            new_id,
            block_id,
            table_id,
            row.get("created_at_utc", datetime.now(UTC)),
        )
    ctx.counts["block_assignments"] = len(assignments)


# ---------------------------------------------------------------------------
# Step 9: Reservations (main entity + junction tables)
# ---------------------------------------------------------------------------
async def migrate_reservations(ctx: MigrationContext) -> None:
    rows = await ctx.legacy.fetch("SELECT * FROM reservations ORDER BY id")
    logger.info("Migrating %d reservations...", len(rows))
    for row in rows:
        new_id = ctx.map_id("reservations", row["id"])
        tenant_id = ctx.get_mapped_id("restaurants", row["restaurant_id"])
        guest_id = ctx.get_mapped_id("guests", row.get("guest_id"))
        table_id = ctx.get_mapped_id("tables", row.get("table_id"))
        if not tenant_id:
            continue
        legacy_notes = (row.get("notes") or "").strip()
        legacy_special_requests = (row.get("special_requests") or "").strip()
        merged_notes_parts = [part for part in [legacy_notes, legacy_special_requests] if part]
        merged_notes = (
            "\n".join(
                merged_notes_parts[idx]
                for idx in range(len(merged_notes_parts))
                if merged_notes_parts[idx] not in merged_notes_parts[:idx]
            )
            or None
        )
        await ctx.execute(
            """INSERT INTO reservations (
                id, tenant_id, guest_id, table_id, start_at, end_at,
                party_size, status, channel, guest_name, guest_email, guest_phone,
                confirmation_code, notes,
                confirmed_at, seated_at, completed_at, canceled_at, canceled_reason, no_show_at,
                tags,
                created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23)
            ON CONFLICT (id) DO NOTHING""",
            new_id,
            tenant_id,
            guest_id,
            table_id,
            row["start_at"],
            row["end_at"],
            row.get("party_size"),
            row.get("status", "pending"),
            row.get("channel", "manual"),
            row.get("guest_name"),
            row.get("guest_email"),
            row.get("guest_phone"),
            row.get("confirmation_code"),
            merged_notes,
            row.get("confirmed_at"),
            row.get("seated_at"),
            row.get("completed_at"),
            row.get("canceled_at"),
            row.get("canceled_reason"),
            row.get("no_show_at"),
            row.get("tags"),
            row.get("created_at_utc", datetime.now(UTC)),
            row.get("updated_at_utc", datetime.now(UTC)),
        )
    ctx.counts["reservations"] = len(rows)

    # Reservation tables
    rt_rows = await ctx.legacy.fetch("SELECT * FROM reservation_tables")
    logger.info("Migrating %d reservation_tables...", len(rt_rows))
    for row in rt_rows:
        res_id = ctx.get_mapped_id("reservations", row["reservation_id"])
        tbl_id = ctx.get_mapped_id("tables", row["table_id"])
        if not res_id or not tbl_id:
            continue
        await ctx.execute(
            """INSERT INTO reservation_tables (reservation_id, table_id, start_at, end_at)
            VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING""",
            res_id,
            tbl_id,
            row.get("start_at"),
            row.get("end_at"),
        )
    ctx.counts["reservation_tables"] = len(rt_rows)


# ---------------------------------------------------------------------------
# Step 10: Table Day Configs
# ---------------------------------------------------------------------------
async def migrate_table_day_configs(ctx: MigrationContext) -> None:
    rows = await ctx.legacy.fetch("SELECT * FROM table_day_configs ORDER BY id")
    logger.info("Migrating %d table_day_configs...", len(rows))
    for row in rows:
        new_id = ctx.map_id("table_day_configs", row["id"])
        tenant_id = ctx.get_mapped_id("restaurants", row["restaurant_id"])
        table_id = ctx.get_mapped_id("tables", row["table_id"])
        if not tenant_id or not table_id:
            continue
        await ctx.execute(
            """INSERT INTO table_day_configs (
                id, tenant_id, table_id, date, is_hidden, is_temporary,
                number, capacity, shape, position_x, position_y,
                width, height, is_active, color, join_group_id,
                is_joinable, rotation, notes, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21)
            ON CONFLICT (id) DO NOTHING""",
            new_id,
            tenant_id,
            table_id,
            row["date"],
            row.get("is_hidden", False),
            row.get("is_temporary", False),
            row.get("number"),
            row.get("capacity"),
            row.get("shape"),
            row.get("position_x"),
            row.get("position_y"),
            row.get("width"),
            row.get("height"),
            row.get("is_active"),
            row.get("color"),
            row.get("join_group_id"),
            row.get("is_joinable"),
            row.get("rotation"),
            row.get("notes"),
            row.get("created_at_utc", datetime.now(UTC)),
            row.get("updated_at_utc", datetime.now(UTC)),
        )
    ctx.counts["table_day_configs"] = len(rows)


# ---------------------------------------------------------------------------
# Step 13: Orders + Items + SumUp Payments
# ---------------------------------------------------------------------------
async def migrate_orders(ctx: MigrationContext) -> None:
    rows = await ctx.legacy.fetch("SELECT * FROM orders ORDER BY id")
    logger.info("Migrating %d orders...", len(rows))
    for row in rows:
        new_id = ctx.map_id("orders", row["id"])
        tenant_id = ctx.get_mapped_id("restaurants", row["restaurant_id"])
        table_id = ctx.get_mapped_id("tables", row.get("table_id"))
        guest_id = ctx.get_mapped_id("guests", row.get("guest_id"))
        res_id = ctx.get_mapped_id("reservations", row.get("reservation_id"))
        created_by = ctx.get_mapped_id("users", row.get("created_by_user_id"))
        if not tenant_id:
            continue
        await ctx.execute(
            """INSERT INTO orders (
                id, tenant_id, table_id, guest_id, reservation_id,
                order_number, status, party_size,
                subtotal, tax_amount_7, tax_amount_19, tax_amount,
                discount_amount, discount_percentage, tip_amount, total,
                payment_method, payment_status, split_payments,
                notes, special_requests,
                opened_at, closed_at, paid_at,
                created_by_user_id, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27)
            ON CONFLICT (id) DO NOTHING""",
            new_id,
            tenant_id,
            table_id,
            guest_id,
            res_id,
            row.get("order_number"),
            row.get("status", "open"),
            row.get("party_size"),
            row.get("subtotal", 0),
            row.get("tax_amount_7", 0),
            row.get("tax_amount_19", 0),
            row.get("tax_amount", 0),
            row.get("discount_amount", 0),
            row.get("discount_percentage"),
            row.get("tip_amount", 0),
            row.get("total", 0),
            row.get("payment_method"),
            row.get("payment_status", "unpaid"),
            row.get("split_payments"),
            row.get("notes"),
            row.get("special_requests"),
            row.get("opened_at"),
            row.get("closed_at"),
            row.get("paid_at"),
            created_by,
            row.get("created_at_utc", datetime.now(UTC)),
            row.get("updated_at_utc", datetime.now(UTC)),
        )
    ctx.counts["orders"] = len(rows)

    # Order items
    items = await ctx.legacy.fetch("SELECT * FROM order_items ORDER BY id")
    logger.info("Migrating %d order_items...", len(items))
    for row in items:
        new_id = ctx.map_id("order_items", row["id"])
        order_id = ctx.get_mapped_id("orders", row["order_id"])
        menu_item_id = ctx.get_mapped_id("menu_items", row.get("menu_item_id"))
        if not order_id:
            continue
        await ctx.execute(
            """INSERT INTO order_items (
                id, order_id, menu_item_id, item_name, item_description,
                category, quantity, unit_price, total_price, tax_rate,
                status, notes, sort_order, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
            ON CONFLICT (id) DO NOTHING""",
            new_id,
            order_id,
            menu_item_id,
            row.get("item_name"),
            row.get("item_description"),
            row.get("category"),
            row.get("quantity", 1),
            row.get("unit_price"),
            row.get("total_price"),
            row.get("tax_rate", 0.19),
            row.get("status", "pending"),
            row.get("notes"),
            row.get("sort_order", 0),
            row.get("created_at_utc", datetime.now(UTC)),
            row.get("updated_at_utc", datetime.now(UTC)),
        )
    ctx.counts["order_items"] = len(items)

    # SumUp payments
    payments = await ctx.legacy.fetch("SELECT * FROM sumup_payments ORDER BY id")
    logger.info("Migrating %d sumup_payments...", len(payments))
    for row in payments:
        new_id = ctx.map_id("sumup_payments", row["id"])
        order_id = ctx.get_mapped_id("orders", row["order_id"])
        tenant_id = ctx.get_mapped_id("restaurants", row["restaurant_id"])
        if not order_id or not tenant_id:
            continue
        await ctx.execute(
            """INSERT INTO sumup_payments (
                id, order_id, tenant_id, checkout_id, client_transaction_id,
                transaction_code, transaction_id, reader_id,
                amount, currency, status, webhook_data,
                initiated_at, completed_at, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
            ON CONFLICT (id) DO NOTHING""",
            new_id,
            order_id,
            tenant_id,
            row.get("checkout_id"),
            row.get("client_transaction_id"),
            row.get("transaction_code"),
            row.get("transaction_id"),
            row.get("reader_id"),
            row.get("amount"),
            row.get("currency", "EUR"),
            row.get("status", "pending"),
            row.get("webhook_data"),
            row.get("initiated_at"),
            row.get("completed_at"),
            row.get("created_at_utc", datetime.now(UTC)),
            row.get("updated_at_utc", datetime.now(UTC)),
        )
    ctx.counts["sumup_payments"] = len(payments)


# ---------------------------------------------------------------------------
# Step 14: Waitlist + Messages
# ---------------------------------------------------------------------------
async def migrate_waitlist_messages(ctx: MigrationContext) -> None:
    wl_rows = await ctx.legacy.fetch("SELECT * FROM waitlist ORDER BY id")
    logger.info("Migrating %d waitlist entries...", len(wl_rows))
    for row in wl_rows:
        new_id = ctx.map_id("waitlist", row["id"])
        tenant_id = ctx.get_mapped_id("restaurants", row["restaurant_id"])
        guest_id = ctx.get_mapped_id("guests", row["guest_id"])
        if not tenant_id or not guest_id:
            continue
        await ctx.execute(
            """INSERT INTO waitlist (
                id, tenant_id, guest_id, party_size, desired_from, desired_to,
                status, priority, notified_at, confirmed_at, notes, created_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            ON CONFLICT (id) DO NOTHING""",
            new_id,
            tenant_id,
            guest_id,
            row.get("party_size"),
            row.get("desired_from"),
            row.get("desired_to"),
            row.get("status", "waiting"),
            row.get("priority"),
            row.get("notified_at"),
            row.get("confirmed_at"),
            row.get("notes"),
            row.get("created_at_utc", datetime.now(UTC)),
        )
    ctx.counts["waitlist"] = len(wl_rows)

    msg_rows = await ctx.legacy.fetch("SELECT * FROM messages ORDER BY id")
    logger.info("Migrating %d messages...", len(msg_rows))
    for row in msg_rows:
        new_id = ctx.map_id("messages", row["id"])
        tenant_id = ctx.get_mapped_id("restaurants", row["restaurant_id"])
        res_id = ctx.get_mapped_id("reservations", row.get("reservation_id"))
        guest_id = ctx.get_mapped_id("guests", row.get("guest_id"))
        if not tenant_id:
            continue
        await ctx.execute(
            """INSERT INTO messages (
                id, tenant_id, reservation_id, guest_id, direction, channel,
                address, body, status, created_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (id) DO NOTHING""",
            new_id,
            tenant_id,
            res_id,
            guest_id,
            row.get("direction"),
            row.get("channel"),
            row.get("address"),
            row.get("body"),
            row.get("status", "queued"),
            row.get("created_at_utc", datetime.now(UTC)),
        )
    ctx.counts["messages"] = len(msg_rows)


# ---------------------------------------------------------------------------
# Step 15: User Settings + Audit Logs
# ---------------------------------------------------------------------------
async def migrate_user_settings_audit(ctx: MigrationContext) -> None:
    us_rows = await ctx.legacy.fetch("SELECT * FROM user_settings ORDER BY id")
    logger.info("Migrating %d user_settings...", len(us_rows))
    for row in us_rows:
        new_id = ctx.map_id("user_settings", row["id"])
        user_id = ctx.get_mapped_id("users", row["user_id"])
        if not user_id:
            continue
        await ctx.execute(
            """INSERT INTO user_settings (id, user_id, settings, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5) ON CONFLICT (id) DO NOTHING""",
            new_id,
            user_id,
            row.get("settings"),
            row.get("created_at_utc", datetime.now(UTC)),
            row.get("updated_at_utc", datetime.now(UTC)),
        )
    ctx.counts["user_settings"] = len(us_rows)

    al_rows = await ctx.legacy.fetch("SELECT * FROM audit_logs ORDER BY id")
    logger.info("Migrating %d audit_logs...", len(al_rows))
    for row in al_rows:
        new_id = ctx.map_id("audit_logs", row["id"])
        tenant_id = ctx.get_mapped_id("restaurants", row["restaurant_id"])
        user_id = ctx.get_mapped_id("users", row.get("user_id"))
        if not tenant_id:
            continue
        await ctx.execute(
            """INSERT INTO audit_logs (
                id, tenant_id, user_id, entity_type, entity_id,
                action, description, details, ip_address, created_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (id) DO NOTHING""",
            new_id,
            tenant_id,
            user_id,
            row.get("entity_type"),
            str(row.get("entity_id", "")),
            row.get("action"),
            row.get("description"),
            row.get("details"),
            row.get("ip_address"),
            row.get("created_at_utc", datetime.now(UTC)),
        )
    ctx.counts["audit_logs"] = len(al_rows)


# ---------------------------------------------------------------------------
# Save ID mapping for rollback
# ---------------------------------------------------------------------------
async def save_id_mapping(ctx: MigrationContext) -> None:
    """Persist the ID mapping table for rollback support."""
    if ctx.dry_run:
        logger.info(
            "DRY-RUN: Would save %d mapping entries", sum(len(v) for v in ctx.id_map.values())
        )
        return

    await ctx.execute("""
        CREATE TABLE IF NOT EXISTS _migration_id_map (
            table_name TEXT NOT NULL,
            old_int_id INTEGER NOT NULL,
            new_uuid UUID NOT NULL,
            migrated_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (table_name, old_int_id)
        )
    """)

    for table_name, mapping in ctx.id_map.items():
        for old_id, new_uuid in mapping.items():
            await ctx.execute(
                """INSERT INTO _migration_id_map (table_name, old_int_id, new_uuid)
                VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
                table_name,
                old_id,
                new_uuid,
            )

    total = sum(len(v) for v in ctx.id_map.values())
    logger.info("Saved %d ID mappings to _migration_id_map", total)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
async def verify_migration(legacy_pool: asyncpg.Pool, target_pool: asyncpg.Pool) -> bool:
    """Compare row counts between legacy and target databases."""
    tables = [
        "restaurants",
        "users",
        "areas",
        "tables",
        "obstacles",
        "guests",
        "menu_categories",
        "menu_items",
        "blocks",
        "block_assignments",
        "reservations",
        "reservation_tables",
        "table_day_configs",
        "orders",
        "order_items",
        "sumup_payments",
        "waitlist",
        "messages",
        "user_settings",
        "audit_logs",
    ]

    all_ok = True
    for table in tables:
        try:
            legacy_count = await legacy_pool.fetchval(f"SELECT COUNT(*) FROM {table}")
        except Exception:
            legacy_count = 0

        try:
            target_count = await target_pool.fetchval(f"SELECT COUNT(*) FROM {table}")
        except Exception:
            target_count = 0

        status = "OK" if legacy_count == target_count else "MISMATCH"
        if status == "MISMATCH":
            all_ok = False
        logger.info("  %-35s legacy=%d  target=%d  [%s]", table, legacy_count, target_count, status)

    return all_ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def run_migration(
    legacy_url: str, target_url: str, dry_run: bool = False, verify_only: bool = False
) -> None:
    legacy_pool = await asyncpg.create_pool(legacy_url, min_size=1, max_size=5)
    target_pool = await asyncpg.create_pool(target_url, min_size=1, max_size=5)

    try:
        if verify_only:
            logger.info("=== VERIFY-ONLY MODE ===")
            ok = await verify_migration(legacy_pool, target_pool)
            if ok:
                logger.info("Verification PASSED: all counts match.")
            else:
                logger.warning("Verification FAILED: count mismatches detected.")
            return

        mode = "DRY-RUN" if dry_run else "LIVE"
        logger.info("=== STARTING MIGRATION (%s) ===", mode)

        ctx = MigrationContext(legacy_pool, target_pool, dry_run=dry_run)

        # Execute in FK-dependency order
        await migrate_restaurants(ctx)
        await migrate_users(ctx)
        await migrate_areas(ctx)
        await migrate_tables(ctx)
        await migrate_obstacles(ctx)
        await migrate_guests(ctx)
        await migrate_menu(ctx)
        await migrate_blocks(ctx)
        await migrate_table_day_configs(ctx)
        await migrate_reservations(ctx)
        await migrate_orders(ctx)
        await migrate_waitlist_messages(ctx)
        await migrate_user_settings_audit(ctx)

        # Save mapping table
        await save_id_mapping(ctx)

        logger.info("=== MIGRATION COMPLETE (%s) ===", mode)
        logger.info("Summary:")
        for table, count in sorted(ctx.counts.items()):
            logger.info("  %-35s %d rows", table, count)

        total = sum(ctx.counts.values())
        logger.info("  %-35s %d rows", "TOTAL", total)

        # Auto-verify
        logger.info("\n=== VERIFICATION ===")
        await verify_migration(legacy_pool, target_pool)

    finally:
        await legacy_pool.close()
        await target_pool.close()


def main():
    parser = argparse.ArgumentParser(
        description="Migrate GastroPilot legacy data to microservices schema"
    )
    parser.add_argument("--legacy-db", required=True, help="Legacy database URL (postgresql://...)")
    parser.add_argument("--target-db", required=True, help="Target database URL (postgresql://...)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate migration without writing")
    parser.add_argument(
        "--verify-only", action="store_true", help="Only verify counts, no migration"
    )
    args = parser.parse_args()

    asyncio.run(
        run_migration(
            args.legacy_db, args.target_db, dry_run=args.dry_run, verify_only=args.verify_only
        )
    )


if __name__ == "__main__":
    main()

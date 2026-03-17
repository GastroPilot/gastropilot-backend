"""Database seeding for the Core microservice (development only).

Creates a full demo dataset so every feature can be tested locally:
- Platform admin user
- Demo restaurant with owner, manager, staff, kitchen users
- Areas, tables (with floor-plan positions)
- Menu categories + items with allergens
- Guests, reservations, waitlist entries
- Guest profile (for guest-portal login)
- Sample orders + order items
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.restaurant import Area, Restaurant, Table
from app.models.user import GuestProfile, User

logger = logging.getLogger(__name__)

# Fixed UUIDs so seed is deterministic and references stay stable across restarts
RESTAURANT_ID = uuid.UUID("00000000-0000-4000-a000-000000000001")
OWNER_ID = uuid.UUID("00000000-0000-4000-a000-000000000010")
MANAGER_ID = uuid.UUID("00000000-0000-4000-a000-000000000011")
STAFF_ID = uuid.UUID("00000000-0000-4000-a000-000000000012")
KITCHEN_ID = uuid.UUID("00000000-0000-4000-a000-000000000013")
AREA_INDOOR_ID = uuid.UUID("00000000-0000-4000-a000-000000000020")
AREA_OUTDOOR_ID = uuid.UUID("00000000-0000-4000-a000-000000000021")
GUEST_PROFILE_ID = uuid.UUID("00000000-0000-4000-a000-000000000030")


async def seed_platform_admin(session: AsyncSession) -> None:
    """Create a platform_admin user if none exists."""
    from shared.auth import hash_password

    from app.core.config import settings

    admin_email = os.environ.get("PLATFORM_ADMIN_EMAIL", "admin@gastropilot.de")
    admin_password = os.environ.get("PLATFORM_ADMIN_PASSWORD")

    if not admin_password:
        if settings.is_development:
            admin_password = "admin1234"
        else:
            return

    result = await session.execute(select(User).where(User.email == admin_email))
    if result.scalar_one_or_none():
        return

    logger.info("Creating platform admin (%s) …", admin_email)
    session.add(
        User(
            email=admin_email,
            password_hash=hash_password(admin_password),
            first_name="Platform",
            last_name="Admin",
            role="platform_admin",
            auth_method="password",
            is_active=True,
        )
    )
    await session.commit()
    logger.info("Platform admin created — email: %s / password: %s", admin_email, admin_password)


async def seed_demo_restaurant(session: AsyncSession) -> None:
    """Create a full demo restaurant with all related data."""
    from shared.auth import hash_password, hash_pin

    # Skip if restaurant already exists
    result = await session.execute(select(Restaurant).where(Restaurant.id == RESTAURANT_ID))
    if result.scalar_one_or_none():
        logger.info("Demo restaurant already exists, skipping seed")
        return

    logger.info("Creating demo restaurant + full dataset …")
    now = datetime.now(timezone.utc)
    today = now.date()

    # ── Restaurant ──────────────────────────────────────────────
    session.add(
        Restaurant(
            id=RESTAURANT_ID,
            name="Bella Vista",
            slug="bella-vista",
            address="Musterstraße 42, 80331 München",
            phone="+49 89 12345678",
            email="info@bellavista-demo.de",
            description="Italienisches Restaurant mit Terrasse – Demo-Tenant",
            public_booking_enabled=True,
            booking_lead_time_hours=2,
            booking_max_party_size=10,
            booking_default_duration=120,
            opening_hours={
                "mon": "11:30-22:00",
                "tue": "11:30-22:00",
                "wed": "11:30-22:00",
                "thu": "11:30-23:00",
                "fri": "11:30-23:30",
                "sat": "12:00-23:30",
                "sun": "12:00-21:00",
            },
            settings={
                "timezone": "Europe/Berlin",
                "currency": "EUR",
                "language": "de",
                "order_number_prefix": "BV",
                "tax_rate": 19.0,
            },
            subscription_tier="professional",
            subscription_status="active",
            is_suspended=False,
        )
    )
    await session.flush()  # Restaurant muss in DB sein bevor FK-Referenzen kommen

    # ── Users ───────────────────────────────────────────────────
    users = [
        User(
            id=OWNER_ID,
            tenant_id=RESTAURANT_ID,
            first_name="Marco",
            last_name="Rossi",
            role="owner",
            auth_method="pin",
            operator_number="0001",
            pin_hash=hash_pin("111111"),
            email="marco@bellavista-demo.de",
            password_hash=hash_password("owner1234"),
            is_active=True,
        ),
        User(
            id=MANAGER_ID,
            tenant_id=RESTAURANT_ID,
            first_name="Laura",
            last_name="Weber",
            role="manager",
            auth_method="pin",
            operator_number="0002",
            pin_hash=hash_pin("222222"),
            is_active=True,
        ),
        User(
            id=STAFF_ID,
            tenant_id=RESTAURANT_ID,
            first_name="Tim",
            last_name="Müller",
            role="staff",
            auth_method="pin",
            operator_number="0003",
            pin_hash=hash_pin("333333"),
            is_active=True,
        ),
        User(
            id=KITCHEN_ID,
            tenant_id=RESTAURANT_ID,
            first_name="Ali",
            last_name="Demir",
            role="kitchen",
            auth_method="pin",
            operator_number="0004",
            pin_hash=hash_pin("444444"),
            is_active=True,
        ),
    ]
    session.add_all(users)

    # ── Areas ───────────────────────────────────────────────────
    session.add_all(
        [
            Area(id=AREA_INDOOR_ID, tenant_id=RESTAURANT_ID, name="Innenbereich"),
            Area(id=AREA_OUTDOOR_ID, tenant_id=RESTAURANT_ID, name="Terrasse"),
        ]
    )

    # ── Tables ──────────────────────────────────────────────────
    tables = []
    # Indoor: 6 tables in a grid
    for i in range(1, 7):
        row, col = divmod(i - 1, 3)
        tables.append(
            Table(
                tenant_id=RESTAURANT_ID,
                area_id=AREA_INDOOR_ID,
                number=str(i),
                capacity=4 if i <= 4 else 6,
                shape="rectangle",
                position_x=100 + col * 200,
                position_y=100 + row * 200,
                width=120,
                height=120,
                is_active=True,
                is_outdoor=False,
            )
        )
    # Outdoor: 4 tables
    for i in range(7, 11):
        tables.append(
            Table(
                tenant_id=RESTAURANT_ID,
                area_id=AREA_OUTDOOR_ID,
                number=str(i),
                capacity=4 if i <= 9 else 8,
                shape="circle" if i <= 9 else "rectangle",
                position_x=100 + (i - 7) * 180,
                position_y=500,
                width=100,
                height=100,
                is_active=True,
                is_outdoor=True,
            )
        )
    session.add_all(tables)
    await session.flush()  # get table IDs

    # ── Menu Categories + Items ─────────────────────────────────
    cat_ids = {
        "antipasti": uuid.uuid4(),
        "pasta": uuid.uuid4(),
        "pizza": uuid.uuid4(),
        "hauptgerichte": uuid.uuid4(),
        "desserts": uuid.uuid4(),
        "getraenke": uuid.uuid4(),
    }
    await session.execute(
        text("""
            INSERT INTO menu_categories (id, tenant_id, name, sort_order, is_active)
            VALUES
                (:antipasti, :tid, 'Antipasti', 1, true),
                (:pasta, :tid, 'Pasta', 2, true),
                (:pizza, :tid, 'Pizza', 3, true),
                (:hauptgerichte, :tid, 'Hauptgerichte', 4, true),
                (:desserts, :tid, 'Desserts', 5, true),
                (:getraenke, :tid, 'Getränke', 6, true)
        """),
        {
            "tid": RESTAURANT_ID,
            "antipasti": cat_ids["antipasti"],
            "pasta": cat_ids["pasta"],
            "pizza": cat_ids["pizza"],
            "hauptgerichte": cat_ids["hauptgerichte"],
            "desserts": cat_ids["desserts"],
            "getraenke": cat_ids["getraenke"],
        },
    )

    menu_items = [
        # Antipasti
        (cat_ids["antipasti"], "Bruschetta Classica", 8.50, 0.19, '["gluten"]'),
        (cat_ids["antipasti"], "Carpaccio di Manzo", 14.90, 0.19, "[]"),
        (cat_ids["antipasti"], "Caprese Salat", 10.50, 0.19, '["milch"]'),
        (cat_ids["antipasti"], "Vitello Tonnato", 13.50, 0.19, '["fisch","eier"]'),
        # Pasta
        (cat_ids["pasta"], "Spaghetti Carbonara", 14.90, 0.19, '["gluten","eier","milch"]'),
        (cat_ids["pasta"], "Tagliatelle al Ragù", 15.90, 0.19, '["gluten"]'),
        (cat_ids["pasta"], "Penne all'Arrabbiata", 12.90, 0.19, '["gluten"]'),
        (cat_ids["pasta"], "Risotto ai Funghi Porcini", 16.90, 0.19, '["milch"]'),
        # Pizza
        (cat_ids["pizza"], "Pizza Margherita", 11.90, 0.19, '["gluten","milch"]'),
        (cat_ids["pizza"], "Pizza Prosciutto e Funghi", 14.50, 0.19, '["gluten","milch"]'),
        (cat_ids["pizza"], "Pizza Diavola", 14.90, 0.19, '["gluten","milch"]'),
        (cat_ids["pizza"], "Pizza Quattro Formaggi", 15.50, 0.19, '["gluten","milch"]'),
        # Hauptgerichte
        (cat_ids["hauptgerichte"], "Saltimbocca alla Romana", 22.90, 0.19, "[]"),
        (cat_ids["hauptgerichte"], "Ossobuco", 24.90, 0.19, '["gluten"]'),
        (cat_ids["hauptgerichte"], "Branzino alla Griglia", 23.50, 0.19, '["fisch"]'),
        # Desserts
        (cat_ids["desserts"], "Tiramisu", 8.90, 0.19, '["gluten","eier","milch"]'),
        (cat_ids["desserts"], "Panna Cotta", 7.50, 0.19, '["milch"]'),
        (cat_ids["desserts"], "Affogato al Caffè", 6.50, 0.19, '["milch"]'),
        # Getränke
        (cat_ids["getraenke"], "Espresso", 2.80, 0.19, "[]"),
        (cat_ids["getraenke"], "Cappuccino", 3.80, 0.19, '["milch"]'),
        (cat_ids["getraenke"], "Aperol Spritz", 8.50, 0.19, "[]"),
        (cat_ids["getraenke"], "Wasser (0,75l)", 4.90, 0.19, "[]"),
        (cat_ids["getraenke"], "Hauswein Rot (0,2l)", 5.90, 0.19, "[]"),
        (cat_ids["getraenke"], "Hauswein Weiß (0,2l)", 5.90, 0.19, "[]"),
    ]
    for idx, (cid, name, price, tax, allergens) in enumerate(menu_items):
        await session.execute(
            text("""
                INSERT INTO menu_items
                    (id, tenant_id, category_id, name, price, tax_rate, is_available,
                     sort_order, allergens)
                VALUES
                    (:id, :tid, :cid, :name, :price, :tax, true, :sort,
                     CAST(:allergens AS jsonb))
            """),
            {
                "id": uuid.uuid4(),
                "tid": RESTAURANT_ID,
                "cid": cid,
                "name": name,
                "price": price,
                "tax": tax,
                "sort": idx + 1,
                "allergens": allergens,
            },
        )

    # ── Guests (CRM) ───────────────────────────────────────────
    guest_ids = [uuid.uuid4() for _ in range(5)]
    guests_data = [
        (guest_ids[0], "Anna", "Schmidt", "anna.schmidt@example.com", "+49 171 1111111"),
        (guest_ids[1], "Thomas", "Fischer", "thomas.fischer@example.com", "+49 172 2222222"),
        (guest_ids[2], "Julia", "Wagner", "julia.wagner@example.com", "+49 173 3333333"),
        (guest_ids[3], "Stefan", "Becker", "stefan.becker@example.com", "+49 174 4444444"),
        (guest_ids[4], "Sophie", "Hoffmann", "sophie.hoffmann@example.com", None),
    ]
    for gid, fn, ln, email, phone in guests_data:
        await session.execute(
            text("""
                INSERT INTO guests (id, tenant_id, first_name, last_name, email, phone)
                VALUES (:id, :tid, :fn, :ln, :email, :phone)
            """),
            {"id": gid, "tid": RESTAURANT_ID, "fn": fn, "ln": ln, "email": email, "phone": phone},
        )

    # ── Reservations (today + coming days) ──────────────────────
    table_ids_result = await session.execute(
        text("SELECT id, number FROM tables WHERE tenant_id = :tid ORDER BY number"),
        {"tid": RESTAURANT_ID},
    )
    table_rows = table_ids_result.fetchall()
    table_map = {row[1]: row[0] for row in table_rows}

    reservations = [
        # Heute Mittag
        (guest_ids[0], table_map.get("1"), today, "12:00", "14:00", 2, "confirmed",
         "Anna", "anna.schmidt@example.com", "+49 171 1111111"),
        # Heute Abend
        (guest_ids[1], table_map.get("3"), today, "19:00", "21:00", 4, "confirmed",
         "Thomas", "thomas.fischer@example.com", "+49 172 2222222"),
        (guest_ids[2], table_map.get("5"), today, "20:00", "22:00", 6, "pending",
         "Julia", "julia.wagner@example.com", "+49 173 3333333"),
        # Morgen
        (guest_ids[3], table_map.get("2"), today + timedelta(days=1), "19:30", "21:30", 2,
         "confirmed", "Stefan", "stefan.becker@example.com", "+49 174 4444444"),
        # Übermorgen
        (guest_ids[4], table_map.get("6"), today + timedelta(days=2), "20:00", "22:00", 8,
         "pending", "Sophie", "sophie.hoffmann@example.com", None),
    ]
    for gid, tid, day, start_h, end_h, psize, status, gname, gemail, gphone in reservations:
        sh, sm = map(int, start_h.split(":"))
        eh, em = map(int, end_h.split(":"))
        start_dt = datetime(day.year, day.month, day.day, sh, sm, tzinfo=timezone.utc)
        end_dt = datetime(day.year, day.month, day.day, eh, em, tzinfo=timezone.utc)
        conf_code = uuid.uuid4().hex[:8].upper()
        await session.execute(
            text("""
                INSERT INTO reservations
                    (id, tenant_id, guest_id, table_id, start_at, end_at, party_size,
                     status, guest_name, guest_email, guest_phone, confirmation_code, channel)
                VALUES
                    (:id, :rest_id, :gid, :tid, :start, :end, :psize,
                     :status, :gname, :gemail, :gphone, :code, 'manual')
            """),
            {
                "id": uuid.uuid4(),
                "rest_id": RESTAURANT_ID,
                "gid": gid,
                "tid": tid,
                "start": start_dt,
                "end": end_dt,
                "psize": psize,
                "status": status,
                "gname": gname,
                "gemail": gemail,
                "gphone": gphone,
                "code": conf_code,
            },
        )

    # ── Waitlist ────────────────────────────────────────────────
    await session.execute(
        text("""
            INSERT INTO waitlist (id, tenant_id, guest_id, party_size, status,
                                  tracking_token, notes)
            VALUES
                (:id1, :tid, :g1, 3, 'waiting', :tk1, 'Müller Party, ca. 20 Min.'),
                (:id2, :tid, :g2, 2, 'waiting', :tk2, 'Klein Party, ca. 35 Min.')
        """),
        {
            "id1": uuid.uuid4(),
            "id2": uuid.uuid4(),
            "tid": RESTAURANT_ID,
            "g1": guest_ids[3],
            "g2": guest_ids[4],
            "tk1": uuid.uuid4().hex[:12],
            "tk2": uuid.uuid4().hex[:12],
        },
    )

    # ── Guest Profile (for guest-portal / table-order login) ───
    from shared.auth import hash_password as hp

    session.add(
        GuestProfile(
            id=GUEST_PROFILE_ID,
            email="gast@example.com",
            first_name="Max",
            last_name="Mustermann",
            phone="+49 170 9999999",
            language="de",
            password_hash=hp("gast1234"),
            email_verified=True,
        )
    )

    # ── Sample Orders + Items ───────────────────────────────────
    # One open order at table 1, one paid order at table 3
    order1_id = uuid.uuid4()
    order2_id = uuid.uuid4()

    # Fetch some menu item IDs for realistic order items
    mi_result = await session.execute(
        text("""
            SELECT id, name, price, category_id FROM menu_items
            WHERE tenant_id = :tid ORDER BY sort_order LIMIT 10
        """),
        {"tid": RESTAURANT_ID},
    )
    mi_rows = mi_result.fetchall()

    # Fetch category names
    cat_result = await session.execute(
        text("SELECT id, name FROM menu_categories WHERE tenant_id = :tid"),
        {"tid": RESTAURANT_ID},
    )
    cat_map = {row[0]: row[1] for row in cat_result.fetchall()}

    await session.execute(
        text("""
            INSERT INTO orders
                (id, tenant_id, table_id, order_number, status, party_size,
                 subtotal, tax_amount_19, tax_amount, total,
                 payment_status, opened_at, created_by_user_id)
            VALUES
                (:o1, :tid, :t1, 'BV-0001', 'open', 2,
                 38.30, 7.28, 7.28, 45.58,
                 'unpaid', :now, :staff),
                (:o2, :tid, :t3, 'BV-0002', 'paid', 4,
                 62.70, 11.91, 11.91, 74.61,
                 'paid', :yesterday, :staff)
        """),
        {
            "o1": order1_id,
            "o2": order2_id,
            "tid": RESTAURANT_ID,
            "t1": table_map.get("1"),
            "t3": table_map.get("3"),
            "now": now,
            "yesterday": now - timedelta(hours=20),
            "staff": STAFF_ID,
        },
    )

    # Order items for order 1 (open)
    if len(mi_rows) >= 4:
        for i, mi in enumerate(mi_rows[:3]):
            mi_id, mi_name, mi_price, mi_cat_id = mi
            await session.execute(
                text("""
                    INSERT INTO order_items
                        (id, order_id, menu_item_id, item_name, category, quantity,
                         unit_price, total_price, tax_rate, status, sort_order, course)
                    VALUES
                        (:id, :oid, :mid, :name, :cat, :qty,
                         :price, :total, 0.19, 'pending', :sort, 1)
                """),
                {
                    "id": uuid.uuid4(),
                    "oid": order1_id,
                    "mid": mi_id,
                    "name": mi_name,
                    "cat": cat_map.get(mi_cat_id, ""),
                    "qty": 1 if i < 2 else 2,
                    "price": float(mi_price),
                    "total": float(mi_price) * (1 if i < 2 else 2),
                    "sort": i + 1,
                },
            )

    # Order items for order 2 (paid)
    if len(mi_rows) >= 8:
        for i, mi in enumerate(mi_rows[4:8]):
            mi_id, mi_name, mi_price, mi_cat_id = mi
            await session.execute(
                text("""
                    INSERT INTO order_items
                        (id, order_id, menu_item_id, item_name, category, quantity,
                         unit_price, total_price, tax_rate, status, sort_order, course)
                    VALUES
                        (:id, :oid, :mid, :name, :cat, 1,
                         :price, :price, 0.19, 'served', :sort, 1)
                """),
                {
                    "id": uuid.uuid4(),
                    "oid": order2_id,
                    "mid": mi_id,
                    "name": mi_name,
                    "cat": cat_map.get(mi_cat_id, ""),
                    "price": float(mi_price),
                    "sort": i + 1,
                },
            )

    await session.commit()

    logger.info("=" * 60)
    logger.info("DEMO SEED COMPLETE — Bella Vista")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Restaurant: Bella Vista (slug: bella-vista)")
    logger.info("")
    logger.info("Staff Logins (PIN auth, tenant_slug=bella-vista):")
    logger.info("  Owner:   0001 / 111111  (Marco Rossi)")
    logger.info("  Manager: 0002 / 222222  (Laura Weber)")
    logger.info("  Staff:   0003 / 333333  (Tim Müller)")
    logger.info("  Kitchen: 0004 / 444444  (Ali Demir)")
    logger.info("")
    logger.info("Owner E-Mail Login:")
    logger.info("  marco@bellavista-demo.de / owner1234")
    logger.info("")
    logger.info("Guest Portal Login:")
    logger.info("  gast@example.com / gast1234")
    logger.info("")
    logger.info("10 Tables (6 indoor, 4 outdoor)")
    logger.info("24 Menu Items in 6 Kategorien")
    logger.info("5 Reservierungen, 2 Warteliste, 2 Bestellungen")
    logger.info("=" * 60)


async def seed_database() -> None:
    """Run all seed functions. Called from lifespan on startup."""
    from app.core.database import get_session_factories

    _, admin_factory = get_session_factories()
    async with admin_factory() as session:
        await seed_platform_admin(session)
        await seed_demo_restaurant(session)

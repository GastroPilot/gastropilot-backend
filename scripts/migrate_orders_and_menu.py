"""
Migration Script: Fügt Orders, OrderItems, MenuItems und MenuCategories hinzu
und erweitert OrderItems um menu_item_id Spalte.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging

from sqlalchemy import text

from app.database.instance import db
from app.settings import DATABASE_URL, DB_TYPE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate():
    """Führt die Migration durch"""
    try:
        async with db.engine.begin() as conn:
            logger.info("Starting migration...")

            # Prüfe ob orders Tabelle existiert
            if DB_TYPE in ["neon", "postgresql"]:
                result = await conn.execute(
                    text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'orders'
                    );
                """)
                )
                orders_exists = result.scalar()
            else:  # SQLite
                result = await conn.execute(
                    text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='orders';
                """)
                )
                orders_exists = result.fetchone() is not None

            if not orders_exists:
                logger.info("Creating orders table...")
                await conn.execute(
                    text("""
                    CREATE TABLE orders (
                        id SERIAL PRIMARY KEY,
                        restaurant_id INTEGER NOT NULL,
                        table_id INTEGER,
                        guest_id INTEGER,
                        order_number VARCHAR(64) UNIQUE,
                        status VARCHAR(32) NOT NULL DEFAULT 'open',
                        party_size INTEGER,
                        subtotal FLOAT NOT NULL DEFAULT 0.0,
                        tax_amount FLOAT NOT NULL DEFAULT 0.0,
                        discount_amount FLOAT NOT NULL DEFAULT 0.0,
                        total FLOAT NOT NULL DEFAULT 0.0,
                        payment_method VARCHAR(32),
                        payment_status VARCHAR(32) NOT NULL DEFAULT 'unpaid',
                        notes TEXT,
                        special_requests TEXT,
                        opened_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                        closed_at TIMESTAMP WITH TIME ZONE,
                        paid_at TIMESTAMP WITH TIME ZONE,
                        created_by_user_id INTEGER,
                        created_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                        updated_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE,
                        FOREIGN KEY (table_id) REFERENCES tables(id) ON DELETE SET NULL,
                        FOREIGN KEY (guest_id) REFERENCES guests(id) ON DELETE SET NULL,
                        FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
                    );
                """)
                )
                await conn.execute(
                    text("CREATE INDEX idx_orders_restaurant_id ON orders(restaurant_id);")
                )
                await conn.execute(text("CREATE INDEX idx_orders_table_id ON orders(table_id);"))
                await conn.execute(text("CREATE INDEX idx_orders_guest_id ON orders(guest_id);"))
                await conn.execute(
                    text("CREATE INDEX idx_orders_order_number ON orders(order_number);")
                )
                await conn.execute(text("CREATE INDEX idx_orders_opened_at ON orders(opened_at);"))
                await conn.execute(
                    text(
                        "CREATE INDEX idx_orders_created_by_user_id ON orders(created_by_user_id);"
                    )
                )
                logger.info("orders table created")
            else:
                logger.info("orders table already exists")

            # Prüfe ob menu_categories Tabelle existiert
            if DB_TYPE in ["neon", "postgresql"]:
                result = await conn.execute(
                    text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'menu_categories'
                    );
                """)
                )
                menu_categories_exists = result.scalar()
            else:
                result = await conn.execute(
                    text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='menu_categories';
                """)
                )
                menu_categories_exists = result.fetchone() is not None

            if not menu_categories_exists:
                logger.info("Creating menu_categories table...")
                await conn.execute(
                    text("""
                    CREATE TABLE menu_categories (
                        id SERIAL PRIMARY KEY,
                        restaurant_id INTEGER NOT NULL,
                        name VARCHAR(100) NOT NULL,
                        description TEXT,
                        sort_order INTEGER,
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                        updated_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE
                    );
                """)
                )
                await conn.execute(
                    text(
                        "CREATE INDEX idx_menu_categories_restaurant_id ON menu_categories(restaurant_id);"
                    )
                )
                logger.info("menu_categories table created")
            else:
                logger.info("menu_categories table already exists")

            # Prüfe ob menu_items Tabelle existiert
            if DB_TYPE in ["neon", "postgresql"]:
                result = await conn.execute(
                    text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'menu_items'
                    );
                """)
                )
                menu_items_exists = result.scalar()
            else:
                result = await conn.execute(
                    text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='menu_items';
                """)
                )
                menu_items_exists = result.fetchone() is not None

            if not menu_items_exists:
                logger.info("Creating menu_items table...")
                await conn.execute(
                    text("""
                    CREATE TABLE menu_items (
                        id SERIAL PRIMARY KEY,
                        restaurant_id INTEGER NOT NULL,
                        category_id INTEGER,
                        name VARCHAR(200) NOT NULL,
                        description TEXT,
                        price FLOAT NOT NULL,
                        is_available BOOLEAN NOT NULL DEFAULT TRUE,
                        sort_order INTEGER,
                        created_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                        updated_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE,
                        FOREIGN KEY (category_id) REFERENCES menu_categories(id) ON DELETE SET NULL
                    );
                """)
                )
                await conn.execute(
                    text("CREATE INDEX idx_menu_items_restaurant_id ON menu_items(restaurant_id);")
                )
                await conn.execute(
                    text("CREATE INDEX idx_menu_items_category_id ON menu_items(category_id);")
                )
                logger.info("menu_items table created")
            else:
                logger.info("menu_items table already exists")

            # Prüfe ob order_items Tabelle existiert
            if DB_TYPE in ["neon", "postgresql"]:
                result = await conn.execute(
                    text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'order_items'
                    );
                """)
                )
                order_items_exists = result.scalar()
            else:
                result = await conn.execute(
                    text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='order_items';
                """)
                )
                order_items_exists = result.fetchone() is not None

            if not order_items_exists:
                logger.info("Creating order_items table...")
                await conn.execute(
                    text("""
                    CREATE TABLE order_items (
                        id SERIAL PRIMARY KEY,
                        order_id INTEGER NOT NULL,
                        menu_item_id INTEGER,
                        item_name VARCHAR(200) NOT NULL,
                        item_description TEXT,
                        category VARCHAR(100),
                        quantity INTEGER NOT NULL DEFAULT 1,
                        unit_price FLOAT NOT NULL,
                        total_price FLOAT NOT NULL,
                        status VARCHAR(32) NOT NULL DEFAULT 'pending',
                        notes TEXT,
                        sort_order INTEGER,
                        created_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                        updated_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                        FOREIGN KEY (menu_item_id) REFERENCES menu_items(id) ON DELETE SET NULL
                    );
                """)
                )
                await conn.execute(
                    text("CREATE INDEX idx_order_items_order_id ON order_items(order_id);")
                )
                await conn.execute(
                    text("CREATE INDEX idx_order_items_menu_item_id ON order_items(menu_item_id);")
                )
                logger.info("order_items table created")
            else:
                # Prüfe ob menu_item_id Spalte existiert
                logger.info("order_items table exists, checking for menu_item_id column...")
                if DB_TYPE in ["neon", "postgresql"]:
                    result = await conn.execute(
                        text("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns 
                            WHERE table_name = 'order_items' 
                            AND column_name = 'menu_item_id'
                        );
                    """)
                    )
                    column_exists = result.scalar()
                else:
                    result = await conn.execute(text("PRAGMA table_info(order_items);"))
                    columns = [row[1] for row in result.fetchall()]
                    column_exists = "menu_item_id" in columns

                if not column_exists:
                    logger.info("Adding menu_item_id column to order_items...")
                    await conn.execute(
                        text("""
                        ALTER TABLE order_items 
                        ADD COLUMN menu_item_id INTEGER;
                    """)
                    )
                    await conn.execute(
                        text("""
                        ALTER TABLE order_items 
                        ADD CONSTRAINT fk_order_items_menu_item_id 
                        FOREIGN KEY (menu_item_id) REFERENCES menu_items(id) ON DELETE SET NULL;
                    """)
                    )
                    await conn.execute(
                        text("""
                        CREATE INDEX idx_order_items_menu_item_id ON order_items(menu_item_id);
                    """)
                    )
                    logger.info("menu_item_id column added")
                else:
                    logger.info("menu_item_id column already exists")

            logger.info("Migration completed successfully!")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(migrate())

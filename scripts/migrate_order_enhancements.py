"""
Migration Script: Fügt Reservierungsverknüpfung, Rabatt, Trinkgeld und Split Payment hinzu
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database.instance import db
from app.settings import DATABASE_URL, DB_TYPE
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate():
    """Führt die Migration durch"""
    try:
        async with db.engine.begin() as conn:
            logger.info("Starting migration for order enhancements...")
            
            # Prüfe ob orders Tabelle existiert
            if DB_TYPE in ["neon", "postgresql"]:
                result = await conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'orders'
                    );
                """))
                orders_exists = result.scalar()
            else:
                result = await conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='orders';
                """))
                orders_exists = result.fetchone() is not None
            
            if not orders_exists:
                logger.error("orders table does not exist. Run migrate_orders_and_menu.py first!")
                return
            
            # Prüfe und füge reservation_id hinzu
            if DB_TYPE in ["neon", "postgresql"]:
                result = await conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'orders' 
                        AND column_name = 'reservation_id'
                    );
                """))
                column_exists = result.scalar()
            else:
                result = await conn.execute(text("PRAGMA table_info(orders);"))
                columns = [row[1] for row in result.fetchall()]
                column_exists = 'reservation_id' in columns
            
            if not column_exists:
                logger.info("Adding reservation_id column to orders...")
                await conn.execute(text("""
                    ALTER TABLE orders 
                    ADD COLUMN reservation_id INTEGER;
                """))
                await conn.execute(text("""
                    ALTER TABLE orders 
                    ADD CONSTRAINT fk_orders_reservation_id 
                    FOREIGN KEY (reservation_id) REFERENCES reservations(id) ON DELETE SET NULL;
                """))
                await conn.execute(text("""
                    CREATE INDEX idx_orders_reservation_id ON orders(reservation_id);
                """))
                logger.info("reservation_id column added")
            else:
                logger.info("reservation_id column already exists")
            
            # Prüfe und füge discount_percentage hinzu
            if DB_TYPE in ["neon", "postgresql"]:
                result = await conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'orders' 
                        AND column_name = 'discount_percentage'
                    );
                """))
                column_exists = result.scalar()
            else:
                result = await conn.execute(text("PRAGMA table_info(orders);"))
                columns = [row[1] for row in result.fetchall()]
                column_exists = 'discount_percentage' in columns
            
            if not column_exists:
                logger.info("Adding discount_percentage column to orders...")
                await conn.execute(text("""
                    ALTER TABLE orders 
                    ADD COLUMN discount_percentage FLOAT;
                """))
                logger.info("discount_percentage column added")
            else:
                logger.info("discount_percentage column already exists")
            
            # Prüfe und füge tip_amount hinzu
            if DB_TYPE in ["neon", "postgresql"]:
                result = await conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'orders' 
                        AND column_name = 'tip_amount'
                    );
                """))
                column_exists = result.scalar()
            else:
                result = await conn.execute(text("PRAGMA table_info(orders);"))
                columns = [row[1] for row in result.fetchall()]
                column_exists = 'tip_amount' in columns
            
            if not column_exists:
                logger.info("Adding tip_amount column to orders...")
                await conn.execute(text("""
                    ALTER TABLE orders 
                    ADD COLUMN tip_amount FLOAT NOT NULL DEFAULT 0.0;
                """))
                logger.info("tip_amount column added")
            else:
                logger.info("tip_amount column already exists")
            
            # Prüfe und füge split_payments hinzu
            if DB_TYPE in ["neon", "postgresql"]:
                result = await conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'orders' 
                        AND column_name = 'split_payments'
                    );
                """))
                column_exists = result.scalar()
            else:
                result = await conn.execute(text("PRAGMA table_info(orders);"))
                columns = [row[1] for row in result.fetchall()]
                column_exists = 'split_payments' in columns
            
            if not column_exists:
                logger.info("Adding split_payments column to orders...")
                if DB_TYPE in ["neon", "postgresql"]:
                    await conn.execute(text("""
                        ALTER TABLE orders 
                        ADD COLUMN split_payments JSON;
                    """))
                else:
                    await conn.execute(text("""
                        ALTER TABLE orders 
                        ADD COLUMN split_payments TEXT;
                    """))
                logger.info("split_payments column added")
            else:
                logger.info("split_payments column already exists")
            
            logger.info("Migration completed successfully!")
            
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(migrate())


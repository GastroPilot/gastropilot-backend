"""
Migration Script: Fügt Allergene und Modifier zu MenuItems hinzu
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
            logger.info("Starting migration for menu enhancements...")
            
            # Prüfe ob menu_items Tabelle existiert
            if DB_TYPE in ["neon", "postgresql"]:
                result = await conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'menu_items'
                    );
                """))
                table_exists = result.scalar()
            else:
                result = await conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='menu_items';
                """))
                table_exists = result.fetchone() is not None
            
            if not table_exists:
                logger.error("menu_items table does not exist. Run migrate_orders_and_menu.py first!")
                return
            
            # Prüfe und füge allergens hinzu
            if DB_TYPE in ["neon", "postgresql"]:
                result = await conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'menu_items' 
                        AND column_name = 'allergens'
                    );
                """))
                column_exists = result.scalar()
            else:
                result = await conn.execute(text("PRAGMA table_info(menu_items);"))
                columns = [row[1] for row in result.fetchall()]
                column_exists = 'allergens' in columns
            
            if not column_exists:
                logger.info("Adding allergens column to menu_items...")
                if DB_TYPE in ["neon", "postgresql"]:
                    await conn.execute(text("""
                        ALTER TABLE menu_items 
                        ADD COLUMN allergens JSON;
                    """))
                else:
                    await conn.execute(text("""
                        ALTER TABLE menu_items 
                        ADD COLUMN allergens TEXT;
                    """))
                logger.info("allergens column added")
            else:
                logger.info("allergens column already exists")
            
            # Prüfe und füge modifiers hinzu
            if DB_TYPE in ["neon", "postgresql"]:
                result = await conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'menu_items' 
                        AND column_name = 'modifiers'
                    );
                """))
                column_exists = result.scalar()
            else:
                result = await conn.execute(text("PRAGMA table_info(menu_items);"))
                columns = [row[1] for row in result.fetchall()]
                column_exists = 'modifiers' in columns
            
            if not column_exists:
                logger.info("Adding modifiers column to menu_items...")
                if DB_TYPE in ["neon", "postgresql"]:
                    await conn.execute(text("""
                        ALTER TABLE menu_items 
                        ADD COLUMN modifiers JSON;
                    """))
                else:
                    await conn.execute(text("""
                        ALTER TABLE menu_items 
                        ADD COLUMN modifiers TEXT;
                    """))
                logger.info("modifiers column added")
            else:
                logger.info("modifiers column already exists")
            
            logger.info("Migration completed successfully!")
            
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(migrate())


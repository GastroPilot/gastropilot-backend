"""
Migration Script: Add tax_rate fields to MenuItem and OrderItem, and tax_amount_7/tax_amount_19 to Order
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.database.instance import db, init_db


async def migrate():
    """Adds tax_rate fields and tax amount breakdown to orders."""
    await init_db()

    async with db.engine.begin() as conn:
        print("Adding tax_rate column to menu_items table...")
        await conn.execute(
            text("""
            ALTER TABLE menu_items 
            ADD COLUMN IF NOT EXISTS tax_rate FLOAT NOT NULL DEFAULT 0.19;
        """)
        )

        print("Adding tax_rate column to order_items table...")
        await conn.execute(
            text("""
            ALTER TABLE order_items 
            ADD COLUMN IF NOT EXISTS tax_rate FLOAT NOT NULL DEFAULT 0.19;
        """)
        )

        print("Adding tax_amount_7 and tax_amount_19 columns to orders table...")
        await conn.execute(
            text("""
            ALTER TABLE orders 
            ADD COLUMN IF NOT EXISTS tax_amount_7 FLOAT NOT NULL DEFAULT 0.0,
            ADD COLUMN IF NOT EXISTS tax_amount_19 FLOAT NOT NULL DEFAULT 0.0;
        """)
        )

        print("Migrating existing tax_amount to tax_amount_19 (assuming 19% for old orders)...")
        await conn.execute(
            text("""
            UPDATE orders 
            SET tax_amount_19 = tax_amount 
            WHERE tax_amount > 0 AND tax_amount_19 = 0;
        """)
        )

        print("Migration completed successfully!")


if __name__ == "__main__":
    asyncio.run(migrate())

"""
Migration: SumUp Integration

Fügt SumUp-Felder zur Restaurant-Tabelle hinzu und erstellt die sumup_payments-Tabelle.
"""

import asyncio
import sys
from pathlib import Path

# Füge das app-Verzeichnis zum Python-Pfad hinzu
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.database.instance import db, init_db
from app.settings import DB_TYPE


async def migrate():
    """Führt die Migration aus."""
    print("Starte Migration: SumUp Integration...")
    await init_db()

    async with db.engine.begin() as conn:
        try:
            if DB_TYPE == "sqlite":
                # SQLite Migration
                print("Führe SQLite-Migration aus...")

                # Füge SumUp-Felder zur restaurants-Tabelle hinzu
                print("Füge SumUp-Felder zur restaurants-Tabelle hinzu...")
                await conn.execute(text("""
                    ALTER TABLE restaurants 
                    ADD COLUMN IF NOT EXISTS sumup_enabled BOOLEAN DEFAULT 0 NOT NULL
                """))
                await conn.execute(text("""
                    ALTER TABLE restaurants 
                    ADD COLUMN IF NOT EXISTS sumup_merchant_code VARCHAR(32)
                """))
                await conn.execute(text("""
                    ALTER TABLE restaurants 
                    ADD COLUMN IF NOT EXISTS sumup_api_key VARCHAR(255)
                """))
                await conn.execute(text("""
                    ALTER TABLE restaurants 
                    ADD COLUMN IF NOT EXISTS sumup_default_reader_id VARCHAR(64)
                """))

                # Erstelle sumup_payments-Tabelle
                print("Erstelle sumup_payments-Tabelle...")
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS sumup_payments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        order_id INTEGER NOT NULL,
                        restaurant_id INTEGER NOT NULL,
                        checkout_id VARCHAR(128),
                        client_transaction_id VARCHAR(128),
                        transaction_code VARCHAR(64),
                        transaction_id VARCHAR(128),
                        reader_id VARCHAR(64),
                        amount REAL NOT NULL,
                        currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
                        status VARCHAR(32) NOT NULL DEFAULT 'pending',
                        webhook_data TEXT,
                        initiated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP,
                        created_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE
                    )
                """))

                # Erstelle Indizes
                print("Erstelle Indizes...")
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_sumup_payments_order_id ON sumup_payments(order_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_sumup_payments_restaurant_id ON sumup_payments(restaurant_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_sumup_payments_checkout_id ON sumup_payments(checkout_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_sumup_payments_client_transaction_id ON sumup_payments(client_transaction_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_sumup_payments_transaction_code ON sumup_payments(transaction_code)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_sumup_payments_transaction_id ON sumup_payments(transaction_id)
                """))

            elif DB_TYPE == "postgresql":
                # PostgreSQL Migration
                print("Führe PostgreSQL-Migration aus...")

                # Füge SumUp-Felder zur restaurants-Tabelle hinzu
                print("Füge SumUp-Felder zur restaurants-Tabelle hinzu...")
                await conn.execute(text("""
                    ALTER TABLE restaurants 
                    ADD COLUMN IF NOT EXISTS sumup_enabled BOOLEAN DEFAULT FALSE NOT NULL
                """))
                await conn.execute(text("""
                    ALTER TABLE restaurants 
                    ADD COLUMN IF NOT EXISTS sumup_merchant_code VARCHAR(32)
                """))
                await conn.execute(text("""
                    ALTER TABLE restaurants 
                    ADD COLUMN IF NOT EXISTS sumup_api_key VARCHAR(255)
                """))
                await conn.execute(text("""
                    ALTER TABLE restaurants 
                    ADD COLUMN IF NOT EXISTS sumup_default_reader_id VARCHAR(64)
                """))

                # Erstelle sumup_payments-Tabelle
                print("Erstelle sumup_payments-Tabelle...")
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS sumup_payments (
                        id SERIAL PRIMARY KEY,
                        order_id INTEGER NOT NULL,
                        restaurant_id INTEGER NOT NULL,
                        checkout_id VARCHAR(128),
                        client_transaction_id VARCHAR(128),
                        transaction_code VARCHAR(64),
                        transaction_id VARCHAR(128),
                        reader_id VARCHAR(64),
                        amount REAL NOT NULL,
                        currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
                        status VARCHAR(32) NOT NULL DEFAULT 'pending',
                        webhook_data JSONB,
                        initiated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP WITH TIME ZONE,
                        created_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE
                    )
                """))

                # Erstelle Indizes
                print("Erstelle Indizes...")
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_sumup_payments_order_id ON sumup_payments(order_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_sumup_payments_restaurant_id ON sumup_payments(restaurant_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_sumup_payments_checkout_id ON sumup_payments(checkout_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_sumup_payments_client_transaction_id ON sumup_payments(client_transaction_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_sumup_payments_transaction_code ON sumup_payments(transaction_code)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_sumup_payments_transaction_id ON sumup_payments(transaction_id)
                """))
            else:
                print(f"Unbekannter DB_TYPE: {DB_TYPE}")
                return

            print("Migration erfolgreich abgeschlossen!")

        except Exception as e:
            print(f"Fehler bei der Migration: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(migrate())

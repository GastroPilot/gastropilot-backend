"""
Migration: Vouchers, Upsell Packages & Prepayments

Fügt die neuen Features hinzu:
- Voucher-System (Gutscheine)
- Upsell-Pakete
- Vorauszahlungen für Reservierungen
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
    print("🔄 Starte Migration: Vouchers, Upsell Packages & Prepayments...")
    await init_db()

    async with db.engine.begin() as conn:
        try:
            if DB_TYPE == "sqlite":
                # SQLite Migration
                print("Führe SQLite-Migration aus...")

                # Füge neue Spalten zur reservations-Tabelle hinzu
                print("Füge neue Spalten zur reservations-Tabelle hinzu...")
                try:
                    await conn.execute(text("""
                        ALTER TABLE reservations 
                        ADD COLUMN voucher_id INTEGER
                    """))
                except Exception:
                    print("  Spalte voucher_id existiert bereits")

                try:
                    await conn.execute(text("""
                        ALTER TABLE reservations 
                        ADD COLUMN voucher_discount_amount REAL
                    """))
                except Exception:
                    print("  Spalte voucher_discount_amount existiert bereits")

                try:
                    await conn.execute(text("""
                        ALTER TABLE reservations 
                        ADD COLUMN prepayment_required BOOLEAN DEFAULT 0 NOT NULL
                    """))
                except Exception:
                    print("  Spalte prepayment_required existiert bereits")

                try:
                    await conn.execute(text("""
                        ALTER TABLE reservations 
                        ADD COLUMN prepayment_amount REAL
                    """))
                except Exception:
                    print("  Spalte prepayment_amount existiert bereits")

                # Erstelle vouchers-Tabelle
                print("Erstelle vouchers-Tabelle...")
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS vouchers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        restaurant_id INTEGER NOT NULL,
                        code VARCHAR(64) NOT NULL,
                        name VARCHAR(240),
                        description TEXT,
                        type VARCHAR(32) NOT NULL DEFAULT 'fixed',
                        value REAL NOT NULL,
                        valid_from DATE,
                        valid_until DATE,
                        max_uses INTEGER,
                        used_count INTEGER NOT NULL DEFAULT 0,
                        min_order_value REAL,
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        created_by_user_id INTEGER,
                        created_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE,
                        FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
                        UNIQUE(restaurant_id, code)
                    )
                """))

                # Erstelle voucher_usage-Tabelle
                print("Erstelle voucher_usage-Tabelle...")
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS voucher_usage (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        voucher_id INTEGER NOT NULL,
                        reservation_id INTEGER,
                        used_by_email VARCHAR(255),
                        discount_amount REAL NOT NULL,
                        used_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (voucher_id) REFERENCES vouchers(id) ON DELETE CASCADE,
                        FOREIGN KEY (reservation_id) REFERENCES reservations(id) ON DELETE SET NULL
                    )
                """))

                # Erstelle upsell_packages-Tabelle
                print("Erstelle upsell_packages-Tabelle...")
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS upsell_packages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        restaurant_id INTEGER NOT NULL,
                        name VARCHAR(240) NOT NULL,
                        description TEXT,
                        price REAL NOT NULL,
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        available_from_date DATE,
                        available_until_date DATE,
                        min_party_size INTEGER,
                        max_party_size INTEGER,
                        available_times TEXT,
                        available_weekdays TEXT,
                        image_url VARCHAR(512),
                        display_order INTEGER NOT NULL DEFAULT 0,
                        created_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE
                    )
                """))

                # Erstelle reservation_prepayments-Tabelle
                print("Erstelle reservation_prepayments-Tabelle...")
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS reservation_prepayments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        reservation_id INTEGER NOT NULL,
                        restaurant_id INTEGER NOT NULL,
                        amount REAL NOT NULL,
                        currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
                        payment_provider VARCHAR(32) NOT NULL,
                        payment_id VARCHAR(128),
                        transaction_id VARCHAR(128),
                        status VARCHAR(32) NOT NULL DEFAULT 'pending',
                        payment_data TEXT,
                        created_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        completed_at_utc TIMESTAMP,
                        FOREIGN KEY (reservation_id) REFERENCES reservations(id) ON DELETE CASCADE,
                        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE
                    )
                """))

                # Erstelle Indizes
                print("Erstelle Indizes...")
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_reservations_voucher_id ON reservations(voucher_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_vouchers_restaurant_id ON vouchers(restaurant_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_vouchers_code ON vouchers(code)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_voucher_usage_voucher_id ON voucher_usage(voucher_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_voucher_usage_reservation_id ON voucher_usage(reservation_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_upsell_packages_restaurant_id ON upsell_packages(restaurant_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_reservation_prepayments_reservation_id ON reservation_prepayments(reservation_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_reservation_prepayments_restaurant_id ON reservation_prepayments(restaurant_id)
                """))

                # Erstelle reservation_upsell_packages-Tabelle
                print("Erstelle reservation_upsell_packages-Tabelle...")
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS reservation_upsell_packages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        reservation_id INTEGER NOT NULL,
                        upsell_package_id INTEGER NOT NULL,
                        price_at_time REAL NOT NULL,
                        created_at_utc TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (reservation_id) REFERENCES reservations(id) ON DELETE CASCADE,
                        FOREIGN KEY (upsell_package_id) REFERENCES upsell_packages(id) ON DELETE CASCADE,
                        UNIQUE(reservation_id, upsell_package_id)
                    )
                """))

                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_reservation_upsell_packages_reservation_id ON reservation_upsell_packages(reservation_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_reservation_upsell_packages_upsell_package_id ON reservation_upsell_packages(upsell_package_id)
                """))

            elif DB_TYPE in ["postgresql", "neon"]:
                # PostgreSQL Migration
                print("Führe PostgreSQL-Migration aus...")

                # Füge neue Spalten zur reservations-Tabelle hinzu
                print("Füge neue Spalten zur reservations-Tabelle hinzu...")
                await conn.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                      WHERE table_name='reservations' AND column_name='voucher_id') THEN
                            ALTER TABLE reservations 
                            ADD COLUMN voucher_id INTEGER;
                        END IF;
                    END $$;
                """))

                await conn.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                      WHERE table_name='reservations' AND column_name='voucher_discount_amount') THEN
                            ALTER TABLE reservations 
                            ADD COLUMN voucher_discount_amount REAL;
                        END IF;
                    END $$;
                """))

                await conn.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                      WHERE table_name='reservations' AND column_name='prepayment_required') THEN
                            ALTER TABLE reservations 
                            ADD COLUMN prepayment_required BOOLEAN DEFAULT FALSE NOT NULL;
                        END IF;
                    END $$;
                """))

                await conn.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                      WHERE table_name='reservations' AND column_name='prepayment_amount') THEN
                            ALTER TABLE reservations 
                            ADD COLUMN prepayment_amount REAL;
                        END IF;
                    END $$;
                """))

                # Erstelle vouchers-Tabelle
                print("Erstelle vouchers-Tabelle...")
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS vouchers (
                        id SERIAL PRIMARY KEY,
                        restaurant_id INTEGER NOT NULL,
                        code VARCHAR(64) NOT NULL,
                        name VARCHAR(240),
                        description TEXT,
                        type VARCHAR(32) NOT NULL DEFAULT 'fixed',
                        value REAL NOT NULL,
                        valid_from DATE,
                        valid_until DATE,
                        max_uses INTEGER,
                        used_count INTEGER NOT NULL DEFAULT 0,
                        min_order_value REAL,
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_by_user_id INTEGER,
                        created_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE,
                        FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
                        UNIQUE(restaurant_id, code)
                    )
                """))

                # Erstelle voucher_usage-Tabelle
                print("Erstelle voucher_usage-Tabelle...")
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS voucher_usage (
                        id SERIAL PRIMARY KEY,
                        voucher_id INTEGER NOT NULL,
                        reservation_id INTEGER,
                        used_by_email VARCHAR(255),
                        discount_amount REAL NOT NULL,
                        used_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (voucher_id) REFERENCES vouchers(id) ON DELETE CASCADE,
                        FOREIGN KEY (reservation_id) REFERENCES reservations(id) ON DELETE SET NULL
                    )
                """))

                # Erstelle upsell_packages-Tabelle
                print("Erstelle upsell_packages-Tabelle...")
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS upsell_packages (
                        id SERIAL PRIMARY KEY,
                        restaurant_id INTEGER NOT NULL,
                        name VARCHAR(240) NOT NULL,
                        description TEXT,
                        price REAL NOT NULL,
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        available_from_date DATE,
                        available_until_date DATE,
                        min_party_size INTEGER,
                        max_party_size INTEGER,
                        available_times JSONB,
                        available_weekdays JSONB,
                        image_url VARCHAR(512),
                        display_order INTEGER NOT NULL DEFAULT 0,
                        created_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE
                    )
                """))

                # Erstelle reservation_prepayments-Tabelle
                print("Erstelle reservation_prepayments-Tabelle...")
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS reservation_prepayments (
                        id SERIAL PRIMARY KEY,
                        reservation_id INTEGER NOT NULL,
                        restaurant_id INTEGER NOT NULL,
                        amount REAL NOT NULL,
                        currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
                        payment_provider VARCHAR(32) NOT NULL,
                        payment_id VARCHAR(128),
                        transaction_id VARCHAR(128),
                        status VARCHAR(32) NOT NULL DEFAULT 'pending',
                        payment_data JSONB,
                        created_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        completed_at_utc TIMESTAMP WITH TIME ZONE,
                        FOREIGN KEY (reservation_id) REFERENCES reservations(id) ON DELETE CASCADE,
                        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE
                    )
                """))

                # Füge Foreign Key für voucher_id hinzu (wenn noch nicht existiert)
                print("Füge Foreign Key Constraints hinzu...")
                await conn.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint 
                            WHERE conname = 'reservations_voucher_id_fkey'
                        ) THEN
                            ALTER TABLE reservations 
                            ADD CONSTRAINT reservations_voucher_id_fkey 
                            FOREIGN KEY (voucher_id) REFERENCES vouchers(id) ON DELETE SET NULL;
                        END IF;
                    END $$;
                """))

                # Erstelle Indizes
                print("Erstelle Indizes...")
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_reservations_voucher_id ON reservations(voucher_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_vouchers_restaurant_id ON vouchers(restaurant_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_vouchers_code ON vouchers(code)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_voucher_usage_voucher_id ON voucher_usage(voucher_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_voucher_usage_reservation_id ON voucher_usage(reservation_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_upsell_packages_restaurant_id ON upsell_packages(restaurant_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_reservation_prepayments_reservation_id ON reservation_prepayments(reservation_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_reservation_prepayments_restaurant_id ON reservation_prepayments(restaurant_id)
                """))

                # Erstelle reservation_upsell_packages-Tabelle
                print("Erstelle reservation_upsell_packages-Tabelle...")
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS reservation_upsell_packages (
                        id SERIAL PRIMARY KEY,
                        reservation_id INTEGER NOT NULL,
                        upsell_package_id INTEGER NOT NULL,
                        price_at_time REAL NOT NULL,
                        created_at_utc TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (reservation_id) REFERENCES reservations(id) ON DELETE CASCADE,
                        FOREIGN KEY (upsell_package_id) REFERENCES upsell_packages(id) ON DELETE CASCADE,
                        UNIQUE(reservation_id, upsell_package_id)
                    )
                """))

                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_reservation_upsell_packages_reservation_id ON reservation_upsell_packages(reservation_id)
                """))
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_reservation_upsell_packages_upsell_package_id ON reservation_upsell_packages(upsell_package_id)
                """))
            else:
                print(f"❌ Unbekannter DB_TYPE: {DB_TYPE}")
                return

            print("✅ Migration erfolgreich abgeschlossen!")

        except Exception as e:
            print(f"❌ Fehler bei der Migration: {e}")
            import traceback

            traceback.print_exc()
            raise


if __name__ == "__main__":
    asyncio.run(migrate())

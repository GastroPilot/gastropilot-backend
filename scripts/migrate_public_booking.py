"""
Migration: Fügt Public Booking Felder zum Restaurant-Modell hinzu.

Neue Felder:
- slug: URL-freundlicher Name für öffentliche Buchungs-URLs
- public_booking_enabled: Flag ob öffentliche Buchungen aktiviert sind
- booking_lead_time_hours: Mindestvorlaufzeit für Buchungen
- booking_max_party_size: Maximale Personenanzahl
- booking_default_duration: Standard-Reservierungsdauer in Minuten
- opening_hours: Öffnungszeiten als JSON
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database.instance import db
from app.settings import DB_TYPE


async def migrate():
    """Führt die Migration aus."""
    
    async with db.engine.begin() as conn:
        print("Starting public booking migration...")
        
        if DB_TYPE == "sqlite":
            # SQLite: Separate ALTER TABLE Statements
            migrations = [
                "ALTER TABLE restaurants ADD COLUMN slug VARCHAR(100) UNIQUE",
                "ALTER TABLE restaurants ADD COLUMN public_booking_enabled BOOLEAN DEFAULT 0",
                "ALTER TABLE restaurants ADD COLUMN booking_lead_time_hours INTEGER DEFAULT 2",
                "ALTER TABLE restaurants ADD COLUMN booking_max_party_size INTEGER DEFAULT 12",
                "ALTER TABLE restaurants ADD COLUMN booking_default_duration INTEGER DEFAULT 120",
                "ALTER TABLE restaurants ADD COLUMN opening_hours TEXT",
            ]
        else:
            # PostgreSQL
            migrations = [
                "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS slug VARCHAR(100) UNIQUE",
                "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS public_booking_enabled BOOLEAN DEFAULT false",
                "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS booking_lead_time_hours INTEGER DEFAULT 2",
                "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS booking_max_party_size INTEGER DEFAULT 12",
                "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS booking_default_duration INTEGER DEFAULT 120",
                "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS opening_hours JSONB",
            ]
        
        for migration in migrations:
            try:
                await conn.execute(text(migration))
                print(f"  ✓ {migration[:60]}...")
            except Exception as e:
                # Column might already exist
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    print(f"  - Column already exists, skipping...")
                else:
                    print(f"  ✗ Error: {e}")
        
        # Create index on slug if not exists
        try:
            if DB_TYPE == "sqlite":
                await conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_restaurants_slug ON restaurants(slug)"
                ))
            else:
                await conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_restaurants_slug ON restaurants(slug)"
                ))
            print("  ✓ Created index on slug")
        except Exception as e:
            print(f"  - Index might already exist: {e}")
        
        print("Migration completed!")


if __name__ == "__main__":
    asyncio.run(migrate())

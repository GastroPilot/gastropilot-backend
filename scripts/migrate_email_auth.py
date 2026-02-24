"""
Migration: Adds email/password authentication support for platform_admin users.

New fields on users table:
- email: Unique email address for platform admin login
- password_hash: bcrypt hash for email/password authentication

Also makes operator_number and pin_hash nullable (platform_admin users
authenticate via email/password instead of operator_number/PIN).
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
    """Runs the migration."""

    async with db.engine.begin() as conn:
        print("Starting email auth migration...")

        if DB_TYPE == "sqlite":
            # SQLite: ADD COLUMN (no IF NOT EXISTS support before 3.35)
            try:
                await conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(255)"))
                print("  + Added email column")
            except Exception:
                print("  ~ email column already exists")

            try:
                await conn.execute(
                    text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)")
                )
                print("  + Added password_hash column")
            except Exception:
                print("  ~ password_hash column already exists")

        else:
            # PostgreSQL: ADD COLUMN IF NOT EXISTS
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255) UNIQUE"
                )
            )
            print("  + Added email column")

            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)"
                )
            )
            print("  + Added password_hash column")

            # Make operator_number and pin_hash nullable for platform_admin users
            await conn.execute(
                text("ALTER TABLE users ALTER COLUMN operator_number DROP NOT NULL")
            )
            print("  + Made operator_number nullable")

            await conn.execute(
                text("ALTER TABLE users ALTER COLUMN pin_hash DROP NOT NULL")
            )
            print("  + Made pin_hash nullable")

            # Create index on email
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_users_email ON users (email) WHERE email IS NOT NULL"
                )
            )
            print("  + Created index on email")

        print("Email auth migration completed successfully!")


if __name__ == "__main__":
    asyncio.run(migrate())

# Import all models to ensure they are registered with Base.metadata
# This ensures that all tables are created when init_db() is called
from app.database import models  # noqa: F401
from app.settings import DATABASE_URL, DB_TYPE

from . import AsyncDatabaseHandler, Base

# Factory for async sessions using the existing database handler.
db = AsyncDatabaseHandler(DATABASE_URL, type=DB_TYPE)
async_session = db.Session


async def init_db():
    """Initialize database by creating all tables."""
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

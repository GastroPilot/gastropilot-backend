import logging
import os
import ssl
from urllib.parse import parse_qs, urlencode, urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

# Base and handler definitions are kept here; instantiation/entrypoints live in app.database.instance
Base = declarative_base()

# Export Base and handler so other modules (e.g., instance.py) can reuse them
__all__ = ["Base", "AsyncDatabaseHandler"]

logger = logging.getLogger(__name__)


class AsyncDatabaseHandler:
    _instance = None
    _initialized = False

    def __new__(cls, db_url, type):
        if cls._instance is None:
            cls._instance = super(AsyncDatabaseHandler, cls).__new__(cls)
        if not cls._initialized:
            cls._instance._initialize(db_url, type)
            cls._initialized = True
        return cls._instance

    def _initialize(self, db_url, type):
        logger.info(f"Initializing database with type: {type}, URL: {db_url[:50]}...")

        # Normalisiere DB-Typ
        type_lower = type.lower().strip()

        if type_lower == "sqlite":
            if db_url.startswith("sqlite+aiosqlite://"):
                database_url = db_url
            else:
                db_path = db_url.replace("\\", "/").lstrip("/")
                database_url = f"sqlite+aiosqlite:///{db_path}"
            connect_args = {}
        elif type_lower in ["neon", "postgresql"]:
            parsed_url = urlparse(db_url)
            # Parse query string to dict
            query_dict = parse_qs(parsed_url.query)
            ssl_enabled = False

            # Check for sslmode
            sslmode_value = None
            if "sslmode" in query_dict:
                sslmode_value = (
                    query_dict["sslmode"][0]
                    if isinstance(query_dict["sslmode"], list)
                    else query_dict["sslmode"]
                )
                del query_dict["sslmode"]

            # Remove channel_binding if present
            if "channel_binding" in query_dict:
                del query_dict["channel_binding"]

            # Rebuild query string (flatten lists to single values for urlencode)
            flat_query_dict = {}
            for key, values in query_dict.items():
                flat_query_dict[key] = (
                    values[0] if isinstance(values, list) and len(values) > 0 else values
                )

            new_query = urlencode(flat_query_dict) if flat_query_dict else ""

            # Reconstruct URL
            if new_query:
                database_url = (
                    f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}?{new_query}"
                )
            else:
                database_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"

            if database_url.startswith("postgresql://"):
                database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif not database_url.startswith("postgresql+asyncpg://"):
                if database_url.startswith("postgresql:"):
                    database_url = database_url.replace("postgresql:", "postgresql+asyncpg:", 1)

            if not database_url.startswith("postgresql+asyncpg://"):
                raise ValueError("Database URL must use postgresql+asyncpg:// driver")

            # SSL-Konfiguration
            if sslmode_value == "disable":
                # SSL komplett deaktivieren
                connect_args = {"ssl": False}
                logger.info("SSL disabled (sslmode=disable)")
            elif sslmode_value in ["verify-full", "verify-ca"]:
                # SSL mit Verifizierung
                ssl_ctx = ssl.create_default_context()
                connect_args = {"ssl": ssl_ctx}
                logger.info("SSL certificate verification enabled (sslmode: %s)", sslmode_value)
            else:
                # SSL ohne Verifizierung (für selbst-signierte Zertifikate)
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
                connect_args = {"ssl": ssl_ctx}
                logger.info(
                    "SSL certificate verification disabled (accepting self-signed certificates)"
                )
        else:
            raise ValueError(
                f"Invalid database type: {type}. Supported types: 'sqlite', 'neon', 'postgresql'"
            )

        if type_lower == "sqlite":
            self.engine = create_async_engine(database_url, connect_args=connect_args, echo=False)
        elif type_lower in ["neon", "postgresql"]:
            self.engine = create_async_engine(
                database_url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
                connect_args=connect_args,
            )
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

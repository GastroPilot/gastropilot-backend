"""
Service für das Erstellen von Activity-Logs in der Datenbank.
"""

import logging

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Activity_Logs

logger = logging.getLogger(__name__)


async def create_activity_log(
    session: AsyncSession,
    action: str,
    user_id: int | None = None,
    ip_address: str | None = None,
    use_own_transaction: bool = True,
) -> None:
    """
    Erstellt einen Activity-Log-Eintrag in der Datenbank.

    Args:
        session: Datenbank-Session
        action: Beschreibung der Aktion
        user_id: Optional - ID des Users, der die Aktion ausgeführt hat
        ip_address: Optional - IP-Adresse des Users
        use_own_transaction: Wenn True, verwendet die Funktion eine eigene Transaktion.
                             Wenn False, wird der Log innerhalb der bestehenden Transaktion erstellt.
    """
    try:
        stmt = insert(Activity_Logs).values(
            action=action,
            user_id=user_id,
            ip_address=ip_address,
        )

        if use_own_transaction:
            async with session.begin():
                await session.execute(stmt)
        else:
            await session.execute(stmt)
    except Exception:
        logger.error("Fehler beim Erstellen eines Activity-Logs", exc_info=True)

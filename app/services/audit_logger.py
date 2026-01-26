"""
Audit-Logger: schreibt strukturierte Audit-Logs in die Datenbank.
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AuditLog

logger = logging.getLogger(__name__)


def _serialize_value(value: Any) -> Any:
    """Stellt sicher, dass Details JSON-serialisierbar sind."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    return value


def _serialize_details(details: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if details is None:
        return None
    return {key: _serialize_value(value) for key, value in details.items()}


async def create_audit_log(
    session: AsyncSession,
    *,
    restaurant_id: Optional[int],
    user_id: Optional[int],
    entity_type: str,
    entity_id: Optional[int],
    action: str,
    description: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    use_own_transaction: bool = False,
) -> None:
    """
    Schreibt einen Audit-Log-Eintrag.
    """
    payload = {
        "restaurant_id": restaurant_id,
        "user_id": user_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "description": description,
        "details": _serialize_details(details),
        "ip_address": ip_address,
    }

    try:
        stmt = insert(AuditLog).values(**payload)

        if use_own_transaction:
            async with session.begin():
                await session.execute(stmt)
        else:
            await session.execute(stmt)
    except Exception:
        logger.exception(
            "Failed to write audit log",
            extra={"entity_type": entity_type, "entity_id": entity_id, "action": action},
        )

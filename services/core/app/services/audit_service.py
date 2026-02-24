from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog, PlatformAuditLog

logger = logging.getLogger(__name__)


async def log_action(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    entity_type: str,
    entity_id: str | None,
    action: str,
    description: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Schreibt einen Eintrag in die tenant-scoped AuditLog-Tabelle."""
    entry = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        description=description,
        details=details,
        ip_address=ip_address,
    )
    session.add(entry)
    try:
        await session.flush()
    except Exception as exc:
        logger.warning("Audit-Log-Eintrag konnte nicht geschrieben werden: %s", exc)


async def log_platform_action(
    session: AsyncSession,
    *,
    admin_user_id: UUID,
    target_tenant_id: UUID | None,
    action: str,
    description: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Schreibt einen plattformweiten Admin-Audit-Log-Eintrag."""
    entry = PlatformAuditLog(
        admin_user_id=admin_user_id,
        target_tenant_id=target_tenant_id,
        action=action,
        description=description,
        details=details,
        ip_address=ip_address,
    )
    session.add(entry)
    try:
        await session.flush()
    except Exception as exc:
        logger.warning("Plattform-Audit-Log konnte nicht geschrieben werden: %s", exc)

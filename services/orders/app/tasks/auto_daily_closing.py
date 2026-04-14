"""Automatic daily closing scheduler.

Runs a background asyncio task that checks at 23:59 local time whether
each tenant with an initialized TSS has already performed a daily closing.
If not, it performs the closing automatically.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

# Berlin timezone (UTC+1 / UTC+2 DST)
try:
    from zoneinfo import ZoneInfo

    LOCAL_TZ = ZoneInfo("Europe/Berlin")
except ImportError:
    LOCAL_TZ = timezone(timedelta(hours=1))

TARGET_HOUR = 23
TARGET_MINUTE = 59


def _seconds_until_target() -> float:
    """Seconds until the next 23:59 local time."""
    now = datetime.now(tz=LOCAL_TZ)
    target = now.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _run_auto_closings() -> None:
    """Perform automatic daily closings for all tenants that haven't closed today."""
    from app.core.database import get_session_factories
    from app.models.fiskaly import FiskalyCashPointClosing, FiskalyTssConfig
    from app.services import fiskaly_service

    today = datetime.now(tz=LOCAL_TZ).strftime("%Y-%m-%d")
    session_factory_app, _ = get_session_factories()

    async with session_factory_app() as db:
        # Get all tenants with initialized TSS
        result = await db.execute(
            select(FiskalyTssConfig).where(FiskalyTssConfig.state == "INITIALIZED")
        )
        configs = list(result.scalars().all())

        for config in configs:
            tenant_id = config.tenant_id
            try:
                # Check if closing already exists for today
                existing = await db.execute(
                    select(FiskalyCashPointClosing).where(
                        FiskalyCashPointClosing.tenant_id == tenant_id,
                        FiskalyCashPointClosing.business_date == today,
                        FiskalyCashPointClosing.state.notin_(["ERROR", "DELETED"]),
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                logger.info(
                    "Auto daily closing for tenant %s, date %s", tenant_id, today
                )
                record = await fiskaly_service.perform_daily_closing(
                    db, tenant_id, today, is_automatic=True
                )
                await db.commit()

                # Trigger DSFinV-K export
                if record.state != "ERROR":
                    try:
                        export_id = uuid.uuid4()
                        await fiskaly_service.dsfinvk_trigger_export(
                            config,
                            export_id,
                            {
                                "business_date_start": today,
                                "business_date_end": today,
                            },
                        )
                        record.dsfinvk_export_id = export_id
                        record.dsfinvk_export_state = "PENDING"
                        await db.commit()
                    except Exception as exc:
                        logger.warning(
                            "Auto DSFinV-K export failed for tenant %s: %s",
                            tenant_id,
                            exc,
                        )

                logger.info(
                    "Auto daily closing completed for tenant %s: state=%s",
                    tenant_id,
                    record.state,
                )
            except ValueError as exc:
                # No paid orders etc. – skip silently
                logger.debug("Auto closing skipped for tenant %s: %s", tenant_id, exc)
            except Exception as exc:
                logger.error(
                    "Auto daily closing failed for tenant %s: %s", tenant_id, exc
                )
                await db.rollback()


async def auto_daily_closing_loop() -> None:
    """Background loop that runs automatic daily closings at 23:59."""
    logger.info("Auto daily closing scheduler started (target: %02d:%02d)", TARGET_HOUR, TARGET_MINUTE)

    while True:
        wait = _seconds_until_target()
        logger.info("Next auto daily closing in %.0f seconds", wait)
        await asyncio.sleep(wait)

        try:
            await _run_auto_closings()
        except Exception as exc:
            logger.error("Auto daily closing loop error: %s", exc)

        # Sleep at least 60s to avoid double-trigger
        await asyncio.sleep(60)

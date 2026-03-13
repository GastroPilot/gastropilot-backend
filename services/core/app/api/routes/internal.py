"""Internal endpoints for cron jobs and service-to-service communication."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_db
from app.models.reservation import Reservation
from app.models.restaurant import Restaurant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


def _verify_internal_key(
    x_internal_key: str = Header(..., alias="X-Internal-Key"),
) -> None:
    if x_internal_key != settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid internal key")


@router.post("/send-reminders")
async def send_reminders(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_internal_key),
):
    """Send reservation reminders for tomorrow's reservations.

    Called daily by a cron job.
    """
    tomorrow = date.today() + timedelta(days=1)

    result = await db.execute(
        select(Reservation, Restaurant)
        .join(
            Restaurant,
            Reservation.tenant_id == Restaurant.id,
        )
        .where(
            and_(
                Reservation.start_at >= tomorrow,
                Reservation.start_at < tomorrow + timedelta(days=1),
                Reservation.status.in_(["pending", "confirmed"]),
                Reservation.reminder_sent.is_(False),
                Reservation.guest_email.isnot(None),
            )
        )
    )
    rows = result.all()

    sent_count = 0
    for reservation, restaurant in rows:
        try:
            from shared.events import event_publisher

            await event_publisher.publish(
                "reservation.reminder",
                {
                    "guest_email": reservation.guest_email,
                    "guest_name": reservation.guest_name or "Gast",
                    "restaurant_name": restaurant.name,
                    "reservation_time": reservation.start_at.strftime("%H:%M"),
                    "party_size": reservation.party_size,
                },
                tenant_id=str(reservation.tenant_id),
            )
            reservation.reminder_sent = True
            sent_count += 1
        except Exception:
            logger.error(
                "Failed to send reminder for reservation %s",
                reservation.id,
            )

    await db.commit()
    logger.info("Sent %d reservation reminders for %s", sent_count, tomorrow)

    return {"sent": sent_count, "date": str(tomorrow)}

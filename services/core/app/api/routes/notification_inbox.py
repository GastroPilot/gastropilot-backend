"""Guest notification inbox endpoints (protected by guest JWT)."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.guest_deps import get_current_guest
from app.models.notification import Notification
from app.models.user import GuestProfile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/notifications", tags=["notification-inbox"])


@router.get("")
async def list_notifications(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
):
    """List notifications for the authenticated guest."""
    offset = (page - 1) * per_page

    result = await db.execute(
        select(Notification)
        .where(Notification.guest_profile_id == guest.id)
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    notifications = result.scalars().all()

    return [
        {
            "id": str(n.id),
            "type": n.type,
            "title": n.title,
            "body": n.body,
            "data": n.data or {},
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notifications
    ]


@router.get("/unread-count")
async def get_unread_count(
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
):
    """Return the number of unread notifications."""
    result = await db.execute(
        select(func.count(Notification.id)).where(
            and_(
                Notification.guest_profile_id == guest.id,
                Notification.is_read.is_(False),
            )
        )
    )
    count = result.scalar() or 0
    return {"unread_count": count}


@router.patch("/{notification_id}/read")
async def mark_as_read(
    notification_id: UUID,
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
):
    """Mark a single notification as read."""
    result = await db.execute(
        select(Notification).where(
            and_(
                Notification.id == notification_id,
                Notification.guest_profile_id == guest.id,
            )
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    notification.is_read = True
    await db.commit()
    return {"id": str(notification.id), "is_read": True}


@router.patch("/read-all")
async def mark_all_read(
    guest: GuestProfile = Depends(get_current_guest),
    db: AsyncSession = Depends(get_db),
):
    """Mark all notifications as read."""
    await db.execute(
        update(Notification)
        .where(
            and_(
                Notification.guest_profile_id == guest.id,
                Notification.is_read.is_(False),
            )
        )
        .values(is_read=True)
    )
    await db.commit()
    return {"message": "All notifications marked as read"}

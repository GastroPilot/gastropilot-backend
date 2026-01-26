from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_session, require_schichtleiter_role
from app.database.models import AuditLog, Restaurant, User
from app.schemas import AuditLogRead

router = APIRouter(prefix="/restaurants/{restaurant_id}/audit-logs", tags=["audit-logs"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


@router.get("/", response_model=list[AuditLogRead])
async def list_audit_logs(
    restaurant_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    entity_type: str | None = Query(None, min_length=1, max_length=50),
    entity_id: int | None = Query(None, ge=1),
    action: str | None = Query(None, min_length=1, max_length=32),
    user_id: int | None = Query(None, ge=1),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Liefert Audit-Logs eines Restaurants (neueste zuerst)."""
    await _get_restaurant_or_404(restaurant_id, session)

    stmt = select(AuditLog).where(AuditLog.restaurant_id == restaurant_id)

    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)

    stmt = stmt.order_by(AuditLog.created_at_utc.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()

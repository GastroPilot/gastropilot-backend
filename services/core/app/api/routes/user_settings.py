from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.models.user import User
from app.models.user_settings import UserSettings

router = APIRouter(prefix="/users/me/settings", tags=["user-settings"])


class UserSettingsUpdate(BaseModel):
    settings: dict


class UserSettingsResponse(BaseModel):
    id: UUID
    user_id: UUID
    settings: dict
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


@router.get("/", response_model=UserSettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == current_user.id))
    settings = result.scalar_one_or_none()
    if not settings:
        settings = UserSettings(user_id=current_user.id, settings={})
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


@router.patch("/", response_model=UserSettingsResponse)
async def update_settings(
    body: UserSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == current_user.id))
    settings = result.scalar_one_or_none()
    if not settings:
        settings = UserSettings(user_id=current_user.id, settings={})
        db.add(settings)
        await db.flush()

    # Merge: update existing keys, add new ones, keep unset
    merged = dict(settings.settings)
    merged.update(body.settings)
    settings.settings = merged

    await db.commit()
    await db.refresh(settings)
    return settings


@router.delete("/{key}", response_model=UserSettingsResponse)
async def delete_setting_key(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == current_user.id))
    settings = result.scalar_one_or_none()
    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found")

    updated = dict(settings.settings)
    updated.pop(key, None)
    settings.settings = updated

    await db.commit()
    await db.refresh(settings)
    return settings

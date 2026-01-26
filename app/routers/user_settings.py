from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User, UserSettings
from app.dependencies import get_session, require_mitarbeiter_role
from app.schemas import UserSettingsRead, UserSettingsUpdate

router = APIRouter(prefix="/users/me/settings", tags=["user-settings"])


async def _get_user_settings(session: AsyncSession, user_id: int) -> UserSettings | None:
    result = await session.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    return result.scalar_one_or_none()


@router.get("/", response_model=UserSettingsRead)
async def get_my_settings(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """
    Liefert die Settings des aktuellen Users. Falls noch keine Settings existieren,
    wird ein leerer Datensatz initialisiert.
    """
    settings = await _get_user_settings(session, current_user.id)
    if settings is None:
        settings = UserSettings(user_id=current_user.id, settings={})
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    return settings


@router.patch("/", response_model=UserSettingsRead)
async def update_my_settings(
    payload: UserSettingsUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """
    Mergt die gelieferten Settings in die bestehenden Settings des aktuellen Users.
    Nicht gesetzte Keys bleiben unverändert.
    """
    incoming = payload.settings or {}
    settings = await _get_user_settings(session, current_user.id)

    if settings is None:
        settings = UserSettings(user_id=current_user.id, settings=incoming)
        session.add(settings)
    else:
        # make a fresh copy so SQLAlchemy sees the change (JSON is not auto-mutable here)
        merged = dict(settings.settings or {})
        merged.update(incoming)
        settings.settings = merged

    await session.commit()
    await session.refresh(settings)
    return settings


@router.delete("/{key}", response_model=UserSettingsRead)
async def delete_my_setting_key(
    key: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """
    Entfernt einen einzelnen Setting-Key des aktuellen Users. Fehlt der Datensatz
    oder der Key, wird ein leerer Zustand bzw. unverändertes Settings-Objekt zurückgegeben.
    """
    settings = await _get_user_settings(session, current_user.id)
    if settings is None:
        settings = UserSettings(user_id=current_user.id, settings={})
        session.add(settings)
    else:
        merged = dict(settings.settings or {})
        if key in merged:
            merged.pop(key, None)
            settings.settings = merged

    await session.commit()
    await session.refresh(settings)
    return settings

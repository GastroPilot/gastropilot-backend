from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_staff_or_above
from app.models.user import User
from app.schemas.menu import AllergenCheckRequest, AllergenCheckResult
from app.services.allergen_service import KNOWN_ALLERGENS, check_menu_items

router = APIRouter(prefix="/allergens", tags=["allergens"])


@router.get("", response_model=list[str])
async def list_allergens():
    """Gibt die Liste aller bekannten Allergen-Bezeichnungen zurück."""
    return sorted(KNOWN_ALLERGENS)


@router.post("/check", response_model=list[AllergenCheckResult])
async def check_allergens(
    body: AllergenCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    """
    Prüft eine Liste von Menü-Items auf Allergen-Kompatibilität
    für einen Gast mit gegebenen Allergenen.
    """
    return await check_menu_items(db, body.item_ids, body.guest_allergens)

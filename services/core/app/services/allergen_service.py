from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.menu import MenuItem
from app.schemas.menu import AllergenCheckResult

# Standardisierte Allergen-Bezeichnungen (EU-14 + erweitert)
KNOWN_ALLERGENS = {
    "gluten",
    "weizen",
    "roggen",
    "gerste",
    "hafer",
    "dinkel",
    "krebstiere",
    "eier",
    "fisch",
    "erdnüsse",
    "soja",
    "milch",
    "schalenfrüchte",
    "mandeln",
    "haselnüsse",
    "walnüsse",
    "cashews",
    "pekannüsse",
    "paranüsse",
    "pistazien",
    "macadamia",
    "sellerie",
    "senf",
    "sesam",
    "schwefeldioxid",
    "sulfite",
    "lupinen",
    "weichtiere",
}

# Alias-Mapping für flexible Eingabe
ALLERGEN_ALIASES: dict[str, str] = {
    "lactose": "milch",
    "dairy": "milch",
    "nuts": "schalenfrüchte",
    "peanut": "erdnüsse",
    "egg": "eier",
    "wheat": "weizen",
    "soy": "soja",
    "shellfish": "krebstiere",
    "sulfites": "sulfite",
    "celery": "sellerie",
    "mustard": "senf",
}


def _normalize_allergen(allergen: str) -> str:
    lower = allergen.strip().lower()
    return ALLERGEN_ALIASES.get(lower, lower)


def check_item_safety(
    item_allergens: list[str],
    item_ingredients: list[dict],
    guest_allergens: list[str],
) -> tuple[bool, list[str]]:
    """
    Prüft ob ein Gericht sicher für die angegebenen Gast-Allergene ist.
    Gibt (is_safe, matched_allergens) zurück.
    """
    normalized_guest = {_normalize_allergen(a) for a in guest_allergens}

    # Allergen-Liste des Gerichts normalisieren
    item_allergen_set = {_normalize_allergen(a) for a in item_allergens}

    # Auch in Zutaten suchen (ingredients ist JSONB: [{name, allergens: []}])
    for ingredient in item_ingredients:
        for allergen in ingredient.get("allergens", []):
            item_allergen_set.add(_normalize_allergen(allergen))

    matches = list(normalized_guest & item_allergen_set)
    return len(matches) == 0, matches


async def check_menu_items(
    session: AsyncSession,
    item_ids: list[UUID],
    guest_allergens: list[str],
) -> list[AllergenCheckResult]:
    if not item_ids:
        return []

    result = await session.execute(select(MenuItem).where(MenuItem.id.in_(item_ids)))
    items = result.scalars().all()

    results = []
    for item in items:
        is_safe, matched = check_item_safety(
            item.allergens or [],
            item.ingredients or [],
            guest_allergens,
        )
        results.append(
            AllergenCheckResult(
                item_id=item.id,
                item_name=item.name,
                is_safe=is_safe,
                matched_allergens=matched,
                ingredients=item.ingredients or [],
            )
        )
    return results

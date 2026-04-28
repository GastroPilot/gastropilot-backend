from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.menu import MenuItem
from app.schemas.menu import AllergenCheckResult

# Standardisierte Allergen-Bezeichnungen (EU-14 + erweitert).
#
# Backend-Aliase decken weiterhin DE/EN-Varianten ab (Backwards-Compat:
# bestehende ``MenuItem.allergens``-Daten und ``GuestProfile.allergen_profile``
# sind teilweise auf Deutsch befüllt). Output wird auf den EU-14-EN-Singular
# normalisiert, wo immer möglich.
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

# Alias-Mapping für flexible Eingabe → kanonische EU-14-EN-Singular-Codes.
# Sowohl DE- als auch EN-Eingaben werden akzeptiert. Output bleibt bei
# unbekannten Codes unverändert (lower-case).
ALLERGEN_ALIASES: dict[str, str] = {
    # Gluten / Cereals
    "gluten": "gluten",
    "weizen": "gluten",
    "wheat": "gluten",
    "roggen": "gluten",
    "rye": "gluten",
    "gerste": "gluten",
    "barley": "gluten",
    "hafer": "gluten",
    "oats": "gluten",
    "dinkel": "gluten",
    "spelt": "gluten",
    # Milk
    "milch": "milk",
    "milk": "milk",
    "lactose": "milk",
    "laktose": "milk",
    "dairy": "milk",
    # Tree nuts
    "schalenfrüchte": "nuts",
    "nuts": "nuts",
    "tree nuts": "nuts",
    "nut": "nuts",
    "mandeln": "nuts",
    "almonds": "nuts",
    "haselnüsse": "nuts",
    "hazelnuts": "nuts",
    "walnüsse": "nuts",
    "walnuts": "nuts",
    "cashews": "nuts",
    "pekannüsse": "nuts",
    "pecans": "nuts",
    "paranüsse": "nuts",
    "brazil nuts": "nuts",
    "pistazien": "nuts",
    "pistachios": "nuts",
    "macadamia": "nuts",
    # Peanuts
    "erdnüsse": "peanuts",
    "erdnuss": "peanuts",
    "peanut": "peanuts",
    "peanuts": "peanuts",
    # Soy
    "soja": "soy",
    "soy": "soy",
    "soya": "soy",
    # Eggs
    "eier": "eggs",
    "ei": "eggs",
    "egg": "eggs",
    "eggs": "eggs",
    # Fish
    "fisch": "fish",
    "fish": "fish",
    # Crustaceans
    "krebstiere": "crustaceans",
    "crustaceans": "crustaceans",
    "shellfish": "crustaceans",
    # Molluscs
    "weichtiere": "molluscs",
    "molluscs": "molluscs",
    "mollusks": "molluscs",
    # Celery
    "sellerie": "celery",
    "celery": "celery",
    # Mustard
    "senf": "mustard",
    "mustard": "mustard",
    # Sesame
    "sesam": "sesame",
    "sesame": "sesame",
    # Sulfites
    "sulfite": "sulfites",
    "sulfites": "sulfites",
    "schwefeldioxid": "sulfites",
    "sulphites": "sulfites",
    # Lupin
    "lupinen": "lupin",
    "lupin": "lupin",
}


def _normalize_allergen(allergen: str) -> str:
    """Normalize a raw allergen string to its canonical EU-14-EN-singular code.

    Falls back to a lower-case stripped version when no alias is known so that
    custom or non-EU-14 codes survive round-trips.
    """
    if not allergen:
        return ""
    lower = allergen.strip().lower()
    return ALLERGEN_ALIASES.get(lower, lower)


def check_item_safety(
    item_allergens: list[str],
    item_ingredients: list[dict],
    guest_allergens: list[str],
) -> tuple[bool, list[str], str, list[str]]:
    """Prüft ob ein Gericht sicher für die angegebenen Gast-Allergene ist.

    Returns ``(is_safe, matched_allergens, risk_level, may_contain)``.

    ``risk_level``:
      - ``"danger"`` — direkter Match zwischen Gast- und Item-Allergenen.
      - ``"warning"`` — Match nur in ``may_contain`` (Spuren).
      - ``"safe"`` — Item hat dokumentierte Allergene/Zutaten, aber kein Match.
      - ``"unknown"`` — weder ``allergens`` noch ``ingredients`` sind beim Item
        gepflegt; eine sichere Aussage ist nicht möglich.
    """
    normalized_guest = {_normalize_allergen(a) for a in guest_allergens if a and a.strip()}

    has_documented_allergens = any(a and a.strip() for a in item_allergens)
    has_documented_ingredients = any(item_ingredients or [])

    # Allergen-Liste des Gerichts normalisieren.
    item_allergen_set: set[str] = {
        _normalize_allergen(a) for a in item_allergens if a and a.strip()
    }

    # Auch in Zutaten suchen (ingredients ist JSONB: [{name, allergens: []}]).
    may_contain: set[str] = set()
    for ingredient in item_ingredients or []:
        for allergen in ingredient.get("allergens", []) or []:
            item_allergen_set.add(_normalize_allergen(allergen))
        for allergen in ingredient.get("may_contain", []) or []:
            may_contain.add(_normalize_allergen(allergen))

    matches = sorted(normalized_guest & item_allergen_set)
    may_contain_matches = sorted(normalized_guest & may_contain)

    if matches:
        risk_level = "danger"
    elif may_contain_matches:
        risk_level = "warning"
    elif not has_documented_allergens and not has_documented_ingredients:
        # Nichts gepflegt → keine belastbare Aussage möglich.
        risk_level = "unknown"
    else:
        risk_level = "safe"

    return len(matches) == 0, matches, risk_level, may_contain_matches


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
        is_safe, matched, risk_level, may_contain = check_item_safety(
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
                risk_level=risk_level,
                may_contain=may_contain,
                ingredients=item.ingredients or [],
            )
        )
    return results

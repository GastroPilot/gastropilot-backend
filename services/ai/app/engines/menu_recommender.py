from __future__ import annotations
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

ALLERGEN_BLOCKLIST: dict[str, list[str]] = {
    "gluten": ["bread", "pasta", "flour", "wheat"],
    "lactose": ["milk", "cheese", "cream", "butter"],
    "nuts": ["peanut", "almond", "walnut", "cashew"],
    "shellfish": ["shrimp", "crab", "lobster"],
    "eggs": ["egg", "mayonnaise"],
}


@dataclass
class MenuRecommendation:
    menu_item_id: str
    score: float
    safe_for_allergens: bool
    reason: str


def recommend_items(
    menu_items: list[dict],
    guest_allergens: list[str] | None = None,
    guest_preferences: dict | None = None,
    top_n: int = 5,
) -> list[MenuRecommendation]:
    """
    Recommends menu items based on guest allergens and preferences.
    Filters out unsafe items and ranks by availability and score.
    """
    guest_allergens = guest_allergens or []

    recommendations = []
    for item in menu_items:
        item_allergens = [a.lower() for a in item.get("allergens", [])]

        # Check allergen safety
        is_safe = True
        for allergen in guest_allergens:
            if allergen.lower() in item_allergens:
                is_safe = False
                break

        if not is_safe:
            continue

        score = 50.0
        if item.get("is_available", True):
            score += 10

        recommendations.append(MenuRecommendation(
            menu_item_id=str(item.get("id", "")),
            score=score,
            safe_for_allergens=True,
            reason="available" if item.get("is_available") else "in menu",
        ))

    recommendations.sort(key=lambda x: x.score, reverse=True)
    return recommendations[:top_n]

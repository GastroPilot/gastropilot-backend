"""Menu recommendation engine with collaborative filtering on order history."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

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
    item_name: str
    score: float
    safe_for_allergens: bool
    reason: str


def recommend_items(
    menu_items: list[dict],
    guest_allergens: list[str] | None = None,
    guest_preferences: dict | None = None,
    order_history: list[dict] | None = None,
    top_n: int = 5,
) -> list[MenuRecommendation]:
    """
    Recommend menu items based on allergens, preferences, and order history.

    Args:
        menu_items: Current menu [{id, name, category, price, allergens, is_available}].
        guest_allergens: Guest's declared allergens.
        guest_preferences: {favorite_categories: [...], dietary: "vegan"|"vegetarian"|None}.
        order_history: Past orders from all guests [{item_id, item_name, quantity, guest_id}].
        top_n: Number of recommendations.
    """
    guest_allergens = guest_allergens or []
    guest_preferences = guest_preferences or {}
    order_history = order_history or []

    # Build popularity index from order history (collaborative filtering)
    popularity: dict[str, int] = defaultdict(int)
    if order_history:
        for entry in order_history:
            iid = str(entry.get("item_id", ""))
            qty = entry.get("quantity", 1)
            popularity[iid] += qty

    max_pop = max(popularity.values()) if popularity else 1

    # Favorite categories
    fav_categories = set(c.lower() for c in guest_preferences.get("favorite_categories", []))
    dietary = guest_preferences.get("dietary", "").lower()

    recommendations: list[MenuRecommendation] = []

    for item in menu_items:
        item_allergens = [a.lower() for a in item.get("allergens", [])]
        item_id = str(item.get("id", ""))
        item_name = item.get("name", "")

        # Hard filter: allergen safety
        is_safe = True
        for allergen in guest_allergens:
            if allergen.lower() in item_allergens:
                is_safe = False
                break
        if not is_safe:
            continue

        # Hard filter: dietary preference
        if dietary == "vegan" and not item.get("is_vegan", False):
            continue
        if dietary == "vegetarian" and not item.get("is_vegetarian", item.get("is_vegan", False)):
            continue

        score = 50.0
        reason_parts: list[str] = []

        # Availability bonus
        if item.get("is_available", True):
            score += 5
        else:
            score -= 20
            reason_parts.append("currently unavailable")

        # Popularity score (0-20 points)
        pop = popularity.get(item_id, 0)
        if pop > 0:
            pop_score = (pop / max_pop) * 20
            score += pop_score
            if pop_score > 15:
                reason_parts.append("very popular")
            elif pop_score > 8:
                reason_parts.append("popular")

        # Category preference
        cat = (item.get("category") or "").lower()
        if cat in fav_categories:
            score += 10
            reason_parts.append("favorite category")

        if not reason_parts:
            reason_parts.append("menu item")

        recommendations.append(
            MenuRecommendation(
                menu_item_id=item_id,
                item_name=item_name,
                score=round(score, 1),
                safe_for_allergens=True,
                reason=", ".join(reason_parts),
            )
        )

    recommendations.sort(key=lambda x: x.score, reverse=True)
    return recommendations[:top_n]

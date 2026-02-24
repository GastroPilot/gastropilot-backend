"""Menu recommendation endpoint with collaborative filtering."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.engines.menu_recommender import recommend_items

router = APIRouter(prefix="/ai/recommendations", tags=["ai-recommendations"])


class RecommendationRequest(BaseModel):
    menu_items: list[dict]
    guest_allergens: list[str] = []
    guest_preferences: dict | None = None
    order_history: list[dict] | None = None
    top_n: int = 5


@router.post("/menu")
async def get_menu_recommendations(data: RecommendationRequest):
    recommendations = recommend_items(
        data.menu_items,
        guest_allergens=data.guest_allergens,
        guest_preferences=data.guest_preferences,
        order_history=data.order_history,
        top_n=data.top_n,
    )
    return {
        "recommendations": [
            {
                "menu_item_id": r.menu_item_id,
                "item_name": r.item_name,
                "score": r.score,
                "safe_for_allergens": r.safe_for_allergens,
                "reason": r.reason,
            }
            for r in recommendations
        ]
    }

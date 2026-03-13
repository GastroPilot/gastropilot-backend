"""Restaurant search schemas for public API."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class RestaurantSearchResponse(BaseModel):
    id: UUID
    name: str
    slug: str | None = None
    address: str | None = None
    cuisine_type: str | None = None
    rating_avg: float | None = None
    rating_count: int = 0
    allergen_safe: list[str] = []
    opening_hours: dict | None = None
    image_url: str | None = None

    model_config = {"from_attributes": True}


class RestaurantDetailResponse(RestaurantSearchResponse):
    description: str | None = None
    phone: str | None = None
    menu_summary: list[dict] = []
    reviews_summary: dict = {}


class RestaurantSearchParams(BaseModel):
    query: str | None = None
    allergens: list[str] | None = None
    cuisine: str | None = None
    location: str | None = None
    page: int = 1
    per_page: int = 20

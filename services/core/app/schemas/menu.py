from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

MenuCategoryType = Literal["food", "drink"]


class MenuCategoryBase(BaseModel):
    name: str
    description: str | None = None
    category_type: MenuCategoryType = "food"
    sort_order: int = 0
    is_active: bool = True


class MenuCategoryCreate(MenuCategoryBase):
    restaurant_id: UUID | None = None


class MenuCategoryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category_type: MenuCategoryType | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class MenuCategoryResponse(MenuCategoryBase):
    id: UUID
    tenant_id: UUID

    model_config = {"from_attributes": True}


class MenuItemBase(BaseModel):
    name: str
    description: str | None = None
    price: float
    category_id: UUID | None = None
    is_available: bool = True
    is_vegetarian: bool = False
    is_vegan: bool = False
    allergens: list[str] = Field(default_factory=list)
    ingredients: list[dict] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    image_url: str | None = None
    sort_order: int = 0

    @field_validator("allergens", "ingredients", "tags", mode="before")
    @classmethod
    def normalize_nullable_lists(cls, value):
        if value is None:
            return []
        return value


class MenuItemCreate(MenuItemBase):
    restaurant_id: UUID | None = None


class MenuItemUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: float | None = None
    category_id: UUID | None = None
    is_available: bool | None = None
    is_vegetarian: bool | None = None
    is_vegan: bool | None = None
    allergens: list[str] | None = None
    ingredients: list[dict] | None = None
    tags: list[str] | None = None
    image_url: str | None = None
    sort_order: int | None = None


class MenuItemResponse(MenuItemBase):
    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AllergenCheckRequest(BaseModel):
    item_ids: list[UUID]
    guest_allergens: list[str]


class AllergenCheckResult(BaseModel):
    item_id: UUID
    item_name: str
    is_safe: bool
    matched_allergens: list[str]
    risk_level: str = "safe"  # "safe" | "warning" | "danger"
    may_contain: list[str] = Field(default_factory=list)
    ingredients: list[dict]

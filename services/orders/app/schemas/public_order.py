"""Public order schemas for guest self-ordering."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PublicMenuItemResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    price: float
    allergens: list = []
    modifiers: dict | None = None

    model_config = {"from_attributes": True}


class PublicMenuCategoryResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    items: list[PublicMenuItemResponse] = []


class PublicMenuResponse(BaseModel):
    restaurant: str
    table_number: str
    categories: list[PublicMenuCategoryResponse] = []


class PublicOrderItemRequest(BaseModel):
    menu_item_id: UUID
    quantity: int = 1
    modifiers: dict | None = None
    special_instructions: str | None = None


class PublicOrderCreateRequest(BaseModel):
    items: list[PublicOrderItemRequest]


class PublicOrderItemResponse(BaseModel):
    id: UUID
    name: str
    quantity: int
    unit_price: float
    total_price: float
    status: str
    special_instructions: str | None = None

    model_config = {"from_attributes": True}


class PublicOrderResponse(BaseModel):
    id: UUID
    session_id: str
    status: str
    items: list[PublicOrderItemResponse] = []
    total: float
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class PublicOrderStatusResponse(BaseModel):
    id: UUID
    status: str
    items: list[PublicOrderItemResponse] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PublicPaymentRequest(BaseModel):
    method: str
    tip_amount: float = 0.0
    split: dict | None = None

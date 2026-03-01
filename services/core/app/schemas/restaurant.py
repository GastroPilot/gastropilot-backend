from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RestaurantBase(BaseModel):
    name: str
    slug: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    timezone: str = "Europe/Berlin"
    currency: str = "EUR"
    language: str = "de"


class RestaurantCreate(RestaurantBase):
    pass


class RestaurantUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    timezone: str | None = None
    currency: str | None = None
    language: str | None = None
    settings: dict | None = None


class RestaurantResponse(RestaurantBase):
    id: UUID
    settings: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# Floor Plan & Table


class AreaBase(BaseModel):
    name: str
    sort_order: int = 0


class AreaCreate(AreaBase):
    pass


class AreaResponse(AreaBase):
    id: UUID
    tenant_id: UUID

    model_config = {"from_attributes": True}


class TableBase(BaseModel):
    name: str
    capacity: int
    min_capacity: int = 1
    is_outdoor: bool = False
    is_joinable: bool = False
    pos_x: float = 0
    pos_y: float = 0
    width: float = 80
    height: float = 80
    area_id: UUID | None = None


class TableCreate(TableBase):
    pass


class TableUpdate(BaseModel):
    name: str | None = None
    capacity: int | None = None
    min_capacity: int | None = None
    is_outdoor: bool | None = None
    is_joinable: bool | None = None
    pos_x: float | None = None
    pos_y: float | None = None
    width: float | None = None
    height: float | None = None
    area_id: UUID | None = None
    is_active: bool | None = None


class TableResponse(TableBase):
    id: UUID
    tenant_id: UUID
    is_active: bool

    model_config = {"from_attributes": True}

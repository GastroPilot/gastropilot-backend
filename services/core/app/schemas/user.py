from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator


class UserBase(BaseModel):
    email: str | None = None
    operator_number: str | None = None
    nfc_tag_id: str | None = None
    first_name: str
    last_name: str
    role: str
    is_active: bool = True


class UserCreate(UserBase):
    password: str | None = None
    pin: str | None = None

    @field_validator("pin")
    @classmethod
    def pin_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) not in (4, 5, 6):
            raise ValueError("PIN muss 4–6 Ziffern haben")
        return v


class UserUpdate(BaseModel):
    email: str | None = None
    operator_number: str | None = None
    nfc_tag_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None
    pin: str | None = None


class UserResponse(BaseModel):
    id: UUID
    tenant_id: UUID | None = None
    email: str | None = None
    operator_number: str | None = None
    nfc_tag_id: str | None = None
    first_name: str
    last_name: str
    role: str
    auth_method: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None

    model_config = {"from_attributes": True}


class UserMeResponse(UserResponse):
    pass

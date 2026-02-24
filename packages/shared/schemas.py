from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class UserRole(StrEnum):
    guest = "guest"
    owner = "owner"
    manager = "manager"
    staff = "staff"
    kitchen = "kitchen"
    platform_admin = "platform_admin"
    platform_support = "platform_support"
    platform_analyst = "platform_analyst"


STAFF_ROLES = {UserRole.owner, UserRole.manager, UserRole.staff, UserRole.kitchen}
PLATFORM_ROLES = {UserRole.platform_admin, UserRole.platform_support, UserRole.platform_analyst}
MANAGEMENT_ROLES = {UserRole.owner, UserRole.manager}


class AuthMethod(StrEnum):
    pin = "pin"
    password = "password"


class ReservationStatus(StrEnum):
    pending = "pending"
    confirmed = "confirmed"
    seated = "seated"
    completed = "completed"
    canceled = "canceled"
    no_show = "no_show"


class OrderStatus(StrEnum):
    open = "open"
    sent_to_kitchen = "sent_to_kitchen"
    in_preparation = "in_preparation"
    ready = "ready"
    served = "served"
    paid = "paid"
    canceled = "canceled"


class OrderItemStatus(StrEnum):
    pending = "pending"
    sent = "sent"
    in_preparation = "in_preparation"
    ready = "ready"
    served = "served"
    canceled = "canceled"


class PaymentStatus(StrEnum):
    unpaid = "unpaid"
    partial = "partial"
    paid = "paid"


class VoucherType(StrEnum):
    fixed = "fixed"
    percentage = "percentage"


class PrepaymentStatus(StrEnum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    refunded = "refunded"


class TokenPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sub: str | None = None
    role: UserRole | None = None
    tenant_id: uuid.UUID | None = None
    impersonating_tenant_id: uuid.UUID | None = None
    auth_method: AuthMethod | None = None
    type: str = "access"
    jti: str | None = None


class TenantContext(BaseModel):
    tenant_id: uuid.UUID | None
    user_id: uuid.UUID
    role: UserRole
    is_admin: bool
    is_impersonating: bool = False


class APIResponse(BaseModel):
    success: bool = True
    message: str | None = None
    data: Any = None


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
    pages: int

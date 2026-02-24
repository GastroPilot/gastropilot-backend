from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class Timestamped(BaseModel):
    created_at_utc: datetime | None = None
    updated_at_utc: datetime | None = None


# Auth Schemas
class LoginRequest(BaseModel):
    # PIN login (staff)
    operator_number: str | None = Field(None, min_length=4, max_length=4, pattern="^[0-9]{4}$")
    pin: str | None = Field(None, min_length=6, max_length=8, pattern="^[0-9]{6,8}$")
    # Email/password login (platform_admin)
    email: EmailStr | None = None
    password: str | None = Field(None, min_length=8, max_length=128)


class NFCLoginRequest(BaseModel):
    nfc_tag_id: str = Field(min_length=1, max_length=64)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class UserRead(Timestamped):
    id: int
    operator_number: str | None = None
    nfc_tag_id: str | None = None
    email: str | None = None
    first_name: str
    last_name: str
    role: str
    is_active: bool
    last_login_at_utc: datetime | None = None

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    operator_number: str | None = Field(None, min_length=4, max_length=4, pattern="^[0-9]{4}$")
    pin: str | None = Field(None, min_length=6, max_length=8, pattern="^[0-9]{6,8}$")
    nfc_tag_id: str | None = Field(None, min_length=1, max_length=64)
    email: EmailStr | None = None
    password: str | None = Field(None, min_length=8, max_length=128)
    first_name: str = Field(min_length=2, max_length=120)
    last_name: str = Field(min_length=2, max_length=120)
    role: str = Field(
        default="mitarbeiter",
        pattern="^(platform_admin|servecta|restaurantinhaber|schichtleiter|mitarbeiter)$",
    )


class UserUpdate(BaseModel):
    operator_number: str | None = Field(None, min_length=4, max_length=4, pattern="^[0-9]{4}$")
    pin: str | None = Field(None, min_length=6, max_length=8, pattern="^[0-9]{6,8}$")
    nfc_tag_id: str | None = Field(None, min_length=1, max_length=64)
    email: EmailStr | None = None
    password: str | None = Field(None, min_length=8, max_length=128)
    first_name: str | None = Field(None, min_length=2, max_length=120)
    last_name: str | None = Field(None, min_length=2, max_length=120)
    role: str | None = Field(
        None, pattern="^(platform_admin|servecta|restaurantinhaber|schichtleiter|mitarbeiter)$"
    )
    is_active: bool | None = None


class UserSettingsRead(Timestamped):
    id: int
    user_id: int
    settings: dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class UserSettingsUpdate(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


# Restaurant Schemas
class RestaurantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(None, min_length=1, max_length=100, pattern="^[a-z0-9-]+$")
    address: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    description: str | None = None
    public_booking_enabled: bool = False
    booking_lead_time_hours: int = Field(default=2, ge=0)
    booking_max_party_size: int = Field(default=12, ge=1)
    booking_default_duration: int = Field(default=120, ge=30)
    opening_hours: dict | None = None


class RestaurantUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    slug: str | None = Field(None, min_length=1, max_length=100, pattern="^[a-z0-9-]+$")
    address: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    description: str | None = None
    public_booking_enabled: bool | None = None
    booking_lead_time_hours: int | None = Field(None, ge=0)
    booking_max_party_size: int | None = Field(None, ge=1)
    booking_default_duration: int | None = Field(None, ge=30)
    opening_hours: dict | None = None
    # SumUp Integration
    # API Key und Merchant Code werden serverseitig verwaltet (nicht überschreibbar)
    sumup_enabled: bool | None = None
    sumup_default_reader_id: str | None = Field(None, max_length=64)


class RestaurantRead(Timestamped):
    id: int
    name: str
    slug: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    description: str | None = None
    public_booking_enabled: bool = False
    booking_lead_time_hours: int = 2
    booking_max_party_size: int = 12
    booking_default_duration: int = 120
    opening_hours: dict | None = None
    # SumUp Integration
    sumup_enabled: bool = False
    sumup_merchant_code: str | None = None
    sumup_default_reader_id: str | None = None

    class Config:
        from_attributes = True


# Table Schemas
class TableCreate(BaseModel):
    number: str = Field(min_length=1, max_length=50)
    capacity: int = Field(gt=0)
    area_id: int | None = None
    shape: str | None = "rectangle"
    position_x: float | None = None
    position_y: float | None = None
    width: float | None = 120.0
    height: float | None = 120.0
    is_active: bool = True
    notes: str | None = None
    # Erweiterte Felder
    is_joinable: bool = False
    join_group_id: int | None = None
    is_outdoor: bool = False
    rotation: int | None = None


class TableUpdate(BaseModel):
    number: str | None = Field(None, min_length=1, max_length=50)
    capacity: int | None = Field(None, gt=0)
    area_id: int | None = None
    shape: str | None = None
    position_x: float | None = None
    position_y: float | None = None
    width: float | None = None
    height: float | None = None
    is_active: bool | None = None
    notes: str | None = None
    # Erweiterte Felder
    is_joinable: bool | None = None
    join_group_id: int | None = None
    is_outdoor: bool | None = None
    rotation: int | None = None


class TableRead(Timestamped):
    id: int
    restaurant_id: int
    area_id: int | None = None
    number: str
    capacity: int
    shape: str | None = None
    position_x: float | None = None
    position_y: float | None = None
    width: float | None = None
    height: float | None = None
    is_active: bool
    notes: str | None = None
    is_joinable: bool
    join_group_id: int | None = None
    is_outdoor: bool
    rotation: int | None = None

    class Config:
        from_attributes = True


# TableDayConfig Schemas
class TableDayConfigCreate(BaseModel):
    table_id: int | None = None  # None für temporäre Tische
    date: date
    is_hidden: bool | None = None
    is_temporary: bool | None = None
    # Für temporäre Tische erforderlich:
    number: str | None = Field(None, max_length=50)
    capacity: int | None = Field(None, gt=0)
    shape: str | None = None
    notes: str | None = None
    # Felder die überschrieben werden können:
    position_x: float | None = None
    position_y: float | None = None
    width: float | None = None
    height: float | None = None
    is_active: bool | None = None
    color: str | None = Field(None, max_length=16)
    join_group_id: int | None = None
    is_joinable: bool | None = None
    rotation: int | None = None


class TableDayConfigUpdate(BaseModel):
    is_hidden: bool | None = None
    number: str | None = Field(None, max_length=50)
    capacity: int | None = Field(None, gt=0)
    shape: str | None = None
    notes: str | None = None
    position_x: float | None = None
    position_y: float | None = None
    width: float | None = None
    height: float | None = None
    is_active: bool | None = None
    color: str | None = Field(None, max_length=16)
    join_group_id: int | None = None
    is_joinable: bool | None = None
    rotation: int | None = None


class TableDayConfigRead(Timestamped):
    id: int
    restaurant_id: int
    table_id: int | None = None
    date: date
    is_hidden: bool
    is_temporary: bool
    number: str | None = None
    capacity: int | None = None
    shape: str | None = None
    notes: str | None = None
    position_x: float | None = None
    position_y: float | None = None
    width: float | None = None
    height: float | None = None
    is_active: bool | None = None
    color: str | None = None
    join_group_id: int | None = None
    is_joinable: bool | None = None
    rotation: int | None = None

    class Config:
        from_attributes = True


# Guest Schemas
class GuestCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    email: EmailStr | None = None
    phone: str | None = None
    language: str | None = Field(None, max_length=10)
    birthday: datetime | None = None
    company: str | None = Field(None, max_length=200)
    type: str | None = Field(None, max_length=50)
    notes: str | None = None


class GuestUpdate(BaseModel):
    first_name: str | None = Field(None, min_length=1, max_length=120)
    last_name: str | None = Field(None, min_length=1, max_length=120)
    email: EmailStr | None = None
    phone: str | None = None
    language: str | None = Field(None, max_length=10)
    birthday: datetime | None = None
    company: str | None = Field(None, max_length=200)
    type: str | None = Field(None, max_length=50)
    notes: str | None = None


class GuestRead(Timestamped):
    id: int
    restaurant_id: int
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    language: str | None = None
    birthday: datetime | None = None
    company: str | None = None
    type: str | None = None
    notes: str | None = None

    class Config:
        from_attributes = True


# Reservation Schemas
class ReservationCreate(BaseModel):
    table_id: int | None = None
    guest_id: int | None = None
    start_at: datetime
    end_at: datetime
    party_size: int = Field(gt=0)
    status: str = "pending"
    channel: str = "manual"
    guest_name: str | None = None
    guest_email: EmailStr | None = None
    guest_phone: str | None = None
    confirmation_code: str | None = None
    special_requests: str | None = None
    notes: str | None = None
    tags: list[str] | None = None


class ReservationUpdate(BaseModel):
    table_id: int | None = None
    guest_id: int | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    party_size: int | None = Field(None, gt=0)
    status: str | None = None
    guest_name: str | None = None
    guest_email: EmailStr | None = None
    guest_phone: str | None = None
    confirmation_code: str | None = None
    special_requests: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    canceled_reason: str | None = None
    no_show_at: datetime | None = None


class ReservationRead(Timestamped):
    id: int
    restaurant_id: int
    table_id: int | None = None
    guest_id: int | None = None
    start_at: datetime
    end_at: datetime
    party_size: int
    status: str
    channel: str
    guest_name: str | None = None
    guest_email: str | None = None
    guest_phone: str | None = None
    confirmation_code: str | None = None
    special_requests: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    confirmed_at: datetime | None = None
    seated_at: datetime | None = None
    completed_at: datetime | None = None
    canceled_at: datetime | None = None
    canceled_reason: str | None = None
    no_show_at: datetime | None = None
    voucher_id: int | None = None
    voucher_discount_amount: float | None = None
    prepayment_required: bool = False
    prepayment_amount: float | None = None
    upsell_packages: list["UpsellPackageRead"] | None = None  # Wird manuell gesetzt

    class Config:
        from_attributes = True


# Areas
class AreaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class AreaUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)


class AreaRead(BaseModel):
    id: int
    restaurant_id: int
    name: str

    class Config:
        from_attributes = True


# Obstacles
class ObstacleCreate(BaseModel):
    area_id: int | None = None
    type: str = Field(min_length=1, max_length=32)
    name: str | None = Field(None, max_length=120)
    x: int
    y: int
    width: int
    height: int
    rotation: int | None = None
    blocking: bool = True
    color: str | None = Field(None, max_length=16)
    notes: str | None = None


class ObstacleUpdate(BaseModel):
    area_id: int | None = None
    type: str | None = Field(None, min_length=1, max_length=32)
    name: str | None = Field(None, max_length=120)
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None
    rotation: int | None = None
    blocking: bool | None = None
    color: str | None = Field(None, max_length=16)
    notes: str | None = None


class ObstacleRead(BaseModel):
    id: int
    restaurant_id: int
    area_id: int | None = None
    type: str
    name: str | None = None
    x: int
    y: int
    width: int
    height: int
    rotation: int | None = None
    blocking: bool
    color: str | None = None
    notes: str | None = None

    class Config:
        from_attributes = True


# Reservation Tables
class ReservationTableCreate(BaseModel):
    reservation_id: int
    table_id: int
    start_at: datetime
    end_at: datetime


class ReservationTableRead(BaseModel):
    reservation_id: int
    table_id: int
    start_at: datetime
    end_at: datetime

    class Config:
        from_attributes = True


class ReservationTableDayConfigCreate(BaseModel):
    reservation_id: int
    table_day_config_id: int
    start_at: datetime
    end_at: datetime


class ReservationTableDayConfigRead(BaseModel):
    reservation_id: int
    table_day_config_id: int
    start_at: datetime
    end_at: datetime

    class Config:
        from_attributes = True


# Block Assignments
class BlockAssignmentCreate(BaseModel):
    block_id: int
    table_id: int


class BlockAssignmentRead(BaseModel):
    id: int
    block_id: int
    table_id: int
    created_at_utc: datetime

    class Config:
        from_attributes = True


# Blocks
class BlockCreate(BaseModel):
    start_at: datetime
    end_at: datetime
    reason: str | None = None


class BlockUpdate(BaseModel):
    start_at: datetime | None = None
    end_at: datetime | None = None
    reason: str | None = None


class BlockRead(BaseModel):
    id: int
    restaurant_id: int
    start_at: datetime
    end_at: datetime
    reason: str | None = None
    created_by_user_id: int | None = None

    class Config:
        from_attributes = True


# Waitlist
class WaitlistCreate(BaseModel):
    guest_id: int | None = None
    party_size: int = Field(gt=0)
    desired_from: datetime | None = None
    desired_to: datetime | None = None
    status: str = "waiting"
    priority: int | None = None
    notes: str | None = None


class WaitlistUpdate(BaseModel):
    guest_id: int | None = None
    party_size: int | None = Field(None, gt=0)
    desired_from: datetime | None = None
    desired_to: datetime | None = None
    status: str | None = None
    priority: int | None = None
    notes: str | None = None
    notified_at: datetime | None = None
    confirmed_at: datetime | None = None


class WaitlistRead(BaseModel):
    id: int
    restaurant_id: int
    guest_id: int | None = None
    party_size: int
    desired_from: datetime | None = None
    desired_to: datetime | None = None
    status: str
    priority: int | None = None
    notified_at: datetime | None = None
    confirmed_at: datetime | None = None
    notes: str | None = None
    created_at_utc: datetime

    class Config:
        from_attributes = True


# Messages
class MessageCreate(BaseModel):
    reservation_id: int | None = None
    guest_id: int | None = None
    direction: str
    channel: str
    address: str
    body: str
    status: str = "queued"


class MessageUpdate(BaseModel):
    status: str | None = None
    body: str | None = None
    channel: str | None = None
    address: str | None = None


class MessageRead(BaseModel):
    id: int
    restaurant_id: int
    reservation_id: int | None = None
    guest_id: int | None = None
    direction: str
    channel: str
    address: str
    body: str
    status: str
    created_at_utc: datetime

    class Config:
        from_attributes = True


# Audit Logs
class AuditLogCreate(BaseModel):
    entity_type: str = Field(min_length=1, max_length=50)
    entity_id: int | None = None
    action: str = Field(min_length=1, max_length=32)
    description: str | None = None
    details: dict[str, Any] | None = None


class AuditLogRead(BaseModel):
    id: int
    restaurant_id: int
    user_id: int | None = None
    entity_type: str
    entity_id: int | None = None
    action: str
    description: str | None = None
    details: dict[str, Any] | None = None
    ip_address: str | None = None
    created_at_utc: datetime

    class Config:
        from_attributes = True


# Order Schemas
class OrderItemCreate(BaseModel):
    item_name: str = Field(min_length=1, max_length=200)
    item_description: str | None = None
    category: str | None = Field(None, max_length=100)
    quantity: int = Field(gt=0, default=1)
    unit_price: float = Field(ge=0)  # Preis inkl. MwSt.
    tax_rate: float | None = Field(None, ge=0, le=1)  # MwSt-Satz
    notes: str | None = None
    sort_order: int | None = 0


class OrderItemUpdate(BaseModel):
    item_name: str | None = Field(None, min_length=1, max_length=200)
    item_description: str | None = None
    category: str | None = Field(None, max_length=100)
    quantity: int | None = Field(None, gt=0)
    unit_price: float | None = Field(None, ge=0)  # Preis inkl. MwSt.
    tax_rate: float | None = Field(None, ge=0, le=1)  # MwSt-Satz
    status: str | None = None
    notes: str | None = None
    sort_order: int | None = None


class OrderItemRead(Timestamped):
    id: int
    order_id: int
    menu_item_id: int | None = None
    item_name: str
    item_description: str | None = None
    category: str | None = None
    quantity: int
    unit_price: float  # Preis inkl. MwSt.
    total_price: float  # Gesamtpreis inkl. MwSt.
    tax_rate: float  # MwSt-Satz
    status: str
    notes: str | None = None
    sort_order: int | None = None

    class Config:
        from_attributes = True


class SplitPayment(BaseModel):
    method: str
    amount: float
    tip_amount: float | None = None
    is_paid: bool | None = False
    item_ids: list[int] | None = None


class OrderCreate(BaseModel):
    table_id: int | None = None
    guest_id: int | None = None
    reservation_id: int | None = None
    party_size: int | None = Field(None, gt=0)
    notes: str | None = None
    special_requests: str | None = None
    split_payments: list[SplitPayment] | None = None
    items: list[OrderItemCreate] | None = None


class OrderUpdate(BaseModel):
    table_id: int | None = None
    guest_id: int | None = None
    reservation_id: int | None = None
    status: str | None = None
    party_size: int | None = Field(None, gt=0)
    subtotal: float | None = Field(None, ge=0)
    tax_amount_7: float | None = Field(None, ge=0)
    tax_amount_19: float | None = Field(None, ge=0)
    tax_amount: float | None = Field(None, ge=0)  # Gesamt-MwSt. (für Kompatibilität)
    discount_amount: float | None = Field(None, ge=0)
    discount_percentage: float | None = Field(None, ge=0, le=100)
    tip_amount: float | None = Field(None, ge=0)
    total: float | None = Field(None, ge=0)
    payment_method: str | None = Field(None, max_length=32)
    payment_status: str | None = None
    split_payments: list[SplitPayment] | None = None
    notes: str | None = None
    special_requests: str | None = None
    closed_at: datetime | None = None
    paid_at: datetime | None = None


class OrderRead(Timestamped):
    id: int
    restaurant_id: int
    table_id: int | None = None
    guest_id: int | None = None
    reservation_id: int | None = None
    order_number: str | None = None
    status: str
    party_size: int | None = None
    subtotal: float  # Zwischensumme inkl. MwSt.
    tax_amount_7: float  # MwSt. bei 7%
    tax_amount_19: float  # MwSt. bei 19%
    tax_amount: float  # Gesamt-MwSt. (für Kompatibilität)
    discount_amount: float
    discount_percentage: float | None = None
    tip_amount: float | None = None
    total: float
    payment_method: str | None = None
    payment_status: str
    split_payments: list[SplitPayment] | None = None
    notes: str | None = None
    special_requests: str | None = None
    opened_at: datetime
    closed_at: datetime | None = None
    paid_at: datetime | None = None
    created_by_user_id: int | None = None

    class Config:
        from_attributes = True


class OrderWithItems(OrderRead):
    items: list[OrderItemRead] = []


# Menu Schemas
class MenuCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    sort_order: int | None = 0
    is_active: bool = True


class MenuCategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class MenuCategoryRead(Timestamped):
    id: int
    restaurant_id: int
    name: str
    description: str | None = None
    sort_order: int | None = None
    is_active: bool

    class Config:
        from_attributes = True


class MenuItemCreate(BaseModel):
    category_id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    price: float = Field(ge=0)  # Preis inkl. MwSt.
    tax_rate: float = Field(default=0.19, ge=0, le=1)  # MwSt-Satz (0.19 = 19%, 0.07 = 7%)
    is_available: bool = True
    sort_order: int | None = 0
    allergens: list[str] | None = None
    modifiers: list[dict] | None = None


class MenuItemUpdate(BaseModel):
    category_id: int | None = None
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    price: float | None = Field(None, ge=0)  # Preis inkl. MwSt.
    tax_rate: float | None = Field(None, ge=0, le=1)  # MwSt-Satz
    is_available: bool | None = None
    sort_order: int | None = None
    allergens: list[str] | None = None
    modifiers: list[dict] | None = None


class MenuItemRead(Timestamped):
    id: int
    restaurant_id: int
    category_id: int | None = None
    name: str
    description: str | None = None
    price: float  # Preis inkl. MwSt.
    tax_rate: float  # MwSt-Satz (0.19 = 19%, 0.07 = 7%)
    is_available: bool
    sort_order: int | None = None
    allergens: list[str] | None = None
    modifiers: list[dict] | None = None

    class Config:
        from_attributes = True


# ============================================================================
# Voucher Schemas
# ============================================================================


class VoucherCreate(BaseModel):
    restaurant_id: int
    code: str = Field(min_length=3, max_length=64)
    name: str | None = None
    description: str | None = None
    type: str = Field(pattern="^(fixed|percentage)$")  # fixed oder percentage
    value: float = Field(gt=0)
    valid_from: date | None = None
    valid_until: date | None = None
    max_uses: int | None = Field(None, gt=0)
    min_order_value: float | None = Field(None, ge=0)
    is_active: bool = True


class VoucherUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    type: str | None = Field(None, pattern="^(fixed|percentage)$")
    value: float | None = Field(None, gt=0)
    valid_from: date | None = None
    valid_until: date | None = None
    max_uses: int | None = Field(None, gt=0)
    min_order_value: float | None = Field(None, ge=0)
    is_active: bool | None = None


class VoucherRead(Timestamped):
    id: int
    restaurant_id: int
    code: str
    name: str | None = None
    description: str | None = None
    type: str
    value: float
    valid_from: date | None = None
    valid_until: date | None = None
    max_uses: int | None = None
    used_count: int
    min_order_value: float | None = None
    is_active: bool

    class Config:
        from_attributes = True


class VoucherValidateRequest(BaseModel):
    code: str
    restaurant_id: int
    reservation_amount: float | None = Field(None, ge=0)  # Betrag der Reservierung für Validierung


class VoucherValidateResponse(BaseModel):
    valid: bool
    voucher: VoucherRead | None = None
    discount_amount: float | None = None  # Berechneter Rabattbetrag
    message: str


# ============================================================================
# Upsell Package Schemas
# ============================================================================


class UpsellPackageCreate(BaseModel):
    restaurant_id: int
    name: str = Field(min_length=1, max_length=240)
    description: str | None = None
    price: float = Field(gt=0)
    is_active: bool = True
    available_from_date: date | None = None
    available_until_date: date | None = None
    min_party_size: int | None = Field(None, gt=0)
    max_party_size: int | None = Field(None, gt=0)
    available_times: dict | None = None  # {"monday": ["18:00", "19:00"], ...}
    available_weekdays: list[int] | None = None  # [0,1,2,3,4,5,6] für Mo-So
    image_url: str | None = None
    display_order: int = 0


class UpsellPackageUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=240)
    description: str | None = None
    price: float | None = Field(None, gt=0)
    is_active: bool | None = None
    available_from_date: date | None = None
    available_until_date: date | None = None
    min_party_size: int | None = Field(None, gt=0)
    max_party_size: int | None = Field(None, gt=0)
    available_times: dict | None = None
    available_weekdays: list[int] | None = None
    image_url: str | None = None
    display_order: int | None = None


class UpsellPackageRead(Timestamped):
    id: int
    restaurant_id: int
    name: str
    description: str | None = None
    price: float
    is_active: bool
    available_from_date: date | None = None
    available_until_date: date | None = None
    min_party_size: int | None = None
    max_party_size: int | None = None
    available_times: dict | None = None
    available_weekdays: list[int] | None = None
    image_url: str | None = None
    display_order: int

    class Config:
        from_attributes = True


class UpsellPackageAvailabilityRequest(BaseModel):
    restaurant_id: int
    date: date
    time: str  # HH:MM Format
    party_size: int = Field(gt=0)


class UpsellPackageAvailabilityResponse(BaseModel):
    packages: list[UpsellPackageRead]


# ============================================================================
# Prepayment Schemas
# ============================================================================


class PrepaymentCreate(BaseModel):
    reservation_id: int
    amount: float = Field(gt=0)
    currency: str = "EUR"
    payment_provider: str = Field(pattern="^(sumup|stripe)$")


class PrepaymentRead(Timestamped):
    id: int
    reservation_id: int
    restaurant_id: int
    amount: float
    currency: str
    payment_provider: str
    payment_id: str | None = None
    transaction_id: str | None = None
    status: str
    payment_data: dict | None = None
    completed_at_utc: datetime | None = None

    class Config:
        from_attributes = True

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Any
from datetime import datetime, date


class Timestamped(BaseModel):
    created_at_utc: Optional[datetime] = None
    updated_at_utc: Optional[datetime] = None


# Auth Schemas
class LoginRequest(BaseModel):
    operator_number: str = Field(min_length=4, max_length=4, pattern="^[0-9]{4}$")
    pin: str = Field(min_length=6, max_length=8, pattern="^[0-9]{6,8}$")


class NFCLoginRequest(BaseModel):
    nfc_tag_id: str = Field(min_length=1, max_length=64)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class UserRead(Timestamped):
    id: int
    operator_number: str
    nfc_tag_id: Optional[str] = None
    first_name: str
    last_name: str
    role: str
    is_active: bool
    last_login_at_utc: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    operator_number: str = Field(min_length=4, max_length=4, pattern="^[0-9]{4}$")
    pin: str = Field(min_length=6, max_length=8, pattern="^[0-9]{6,8}$")
    nfc_tag_id: Optional[str] = Field(None, min_length=1, max_length=64)
    first_name: str = Field(min_length=2, max_length=120)
    last_name: str = Field(min_length=2, max_length=120)
    role: str = Field(default="mitarbeiter", pattern="^(servecta|restaurantinhaber|schichtleiter|mitarbeiter)$")


class UserUpdate(BaseModel):
    operator_number: Optional[str] = Field(None, min_length=4, max_length=4, pattern="^[0-9]{4}$")
    pin: Optional[str] = Field(None, min_length=6, max_length=8, pattern="^[0-9]{6,8}$")
    nfc_tag_id: Optional[str] = Field(None, min_length=1, max_length=64)
    first_name: Optional[str] = Field(None, min_length=2, max_length=120)
    last_name: Optional[str] = Field(None, min_length=2, max_length=120)
    role: Optional[str] = Field(None, pattern="^(servecta|restaurantinhaber|schichtleiter|mitarbeiter)$")
    is_active: Optional[bool] = None


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
    slug: Optional[str] = Field(None, min_length=1, max_length=100, pattern="^[a-z0-9-]+$")
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    description: Optional[str] = None
    public_booking_enabled: bool = False
    booking_lead_time_hours: int = Field(default=2, ge=0)
    booking_max_party_size: int = Field(default=12, ge=1)
    booking_default_duration: int = Field(default=120, ge=30)
    opening_hours: Optional[dict] = None


class RestaurantUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    slug: Optional[str] = Field(None, min_length=1, max_length=100, pattern="^[a-z0-9-]+$")
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    description: Optional[str] = None
    public_booking_enabled: Optional[bool] = None
    booking_lead_time_hours: Optional[int] = Field(None, ge=0)
    booking_max_party_size: Optional[int] = Field(None, ge=1)
    booking_default_duration: Optional[int] = Field(None, ge=30)
    opening_hours: Optional[dict] = None
    # SumUp Integration
    # API Key und Merchant Code werden serverseitig verwaltet (nicht überschreibbar)
    sumup_enabled: Optional[bool] = None
    sumup_default_reader_id: Optional[str] = Field(None, max_length=64)


class RestaurantRead(Timestamped):
    id: int
    name: str
    slug: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    description: Optional[str] = None
    public_booking_enabled: bool = False
    booking_lead_time_hours: int = 2
    booking_max_party_size: int = 12
    booking_default_duration: int = 120
    opening_hours: Optional[dict] = None
    # SumUp Integration
    sumup_enabled: bool = False
    sumup_merchant_code: Optional[str] = None
    sumup_default_reader_id: Optional[str] = None

    class Config:
        from_attributes = True


# Table Schemas
class TableCreate(BaseModel):
    number: str = Field(min_length=1, max_length=50)
    capacity: int = Field(gt=0)
    area_id: Optional[int] = None
    shape: Optional[str] = "rectangle"
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    width: Optional[float] = 120.0
    height: Optional[float] = 120.0
    is_active: bool = True
    notes: Optional[str] = None
    # Erweiterte Felder
    is_joinable: bool = False
    join_group_id: Optional[int] = None
    is_outdoor: bool = False
    rotation: Optional[int] = None


class TableUpdate(BaseModel):
    number: Optional[str] = Field(None, min_length=1, max_length=50)
    capacity: Optional[int] = Field(None, gt=0)
    area_id: Optional[int] = None
    shape: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None
    # Erweiterte Felder
    is_joinable: Optional[bool] = None
    join_group_id: Optional[int] = None
    is_outdoor: Optional[bool] = None
    rotation: Optional[int] = None


class TableRead(Timestamped):
    id: int
    restaurant_id: int
    area_id: Optional[int] = None
    number: str
    capacity: int
    shape: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    is_active: bool
    notes: Optional[str] = None
    is_joinable: bool
    join_group_id: Optional[int] = None
    is_outdoor: bool
    rotation: Optional[int] = None

    class Config:
        from_attributes = True


# TableDayConfig Schemas
class TableDayConfigCreate(BaseModel):
    table_id: Optional[int] = None  # None für temporäre Tische
    date: date
    is_hidden: Optional[bool] = None
    is_temporary: Optional[bool] = None
    # Für temporäre Tische erforderlich:
    number: Optional[str] = Field(None, max_length=50)
    capacity: Optional[int] = Field(None, gt=0)
    shape: Optional[str] = None
    notes: Optional[str] = None
    # Felder die überschrieben werden können:
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    is_active: Optional[bool] = None
    color: Optional[str] = Field(None, max_length=16)
    join_group_id: Optional[int] = None
    is_joinable: Optional[bool] = None
    rotation: Optional[int] = None


class TableDayConfigUpdate(BaseModel):
    is_hidden: Optional[bool] = None
    number: Optional[str] = Field(None, max_length=50)
    capacity: Optional[int] = Field(None, gt=0)
    shape: Optional[str] = None
    notes: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    is_active: Optional[bool] = None
    color: Optional[str] = Field(None, max_length=16)
    join_group_id: Optional[int] = None
    is_joinable: Optional[bool] = None
    rotation: Optional[int] = None


class TableDayConfigRead(Timestamped):
    id: int
    restaurant_id: int
    table_id: Optional[int] = None
    date: date
    is_hidden: bool
    is_temporary: bool
    number: Optional[str] = None
    capacity: Optional[int] = None
    shape: Optional[str] = None
    notes: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    is_active: Optional[bool] = None
    color: Optional[str] = None
    join_group_id: Optional[int] = None
    is_joinable: Optional[bool] = None
    rotation: Optional[int] = None

    class Config:
        from_attributes = True


# Guest Schemas
class GuestCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    language: Optional[str] = Field(None, max_length=10)
    birthday: Optional[datetime] = None
    company: Optional[str] = Field(None, max_length=200)
    type: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None


class GuestUpdate(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=120)
    last_name: Optional[str] = Field(None, min_length=1, max_length=120)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    language: Optional[str] = Field(None, max_length=10)
    birthday: Optional[datetime] = None
    company: Optional[str] = Field(None, max_length=200)
    type: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None


class GuestRead(Timestamped):
    id: int
    restaurant_id: int
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    language: Optional[str] = None
    birthday: Optional[datetime] = None
    company: Optional[str] = None
    type: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


# Reservation Schemas
class ReservationCreate(BaseModel):
    table_id: Optional[int] = None
    guest_id: Optional[int] = None
    start_at: datetime
    end_at: datetime
    party_size: int = Field(gt=0)
    status: str = "pending"
    channel: str = "manual"
    guest_name: Optional[str] = None
    guest_email: Optional[EmailStr] = None
    guest_phone: Optional[str] = None
    confirmation_code: Optional[str] = None
    special_requests: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class ReservationUpdate(BaseModel):
    table_id: Optional[int] = None
    guest_id: Optional[int] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    party_size: Optional[int] = Field(None, gt=0)
    status: Optional[str] = None
    guest_name: Optional[str] = None
    guest_email: Optional[EmailStr] = None
    guest_phone: Optional[str] = None
    confirmation_code: Optional[str] = None
    special_requests: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    canceled_reason: Optional[str] = None
    no_show_at: Optional[datetime] = None


class ReservationRead(Timestamped):
    id: int
    restaurant_id: int
    table_id: Optional[int] = None
    guest_id: Optional[int] = None
    start_at: datetime
    end_at: datetime
    party_size: int
    status: str
    channel: str
    guest_name: Optional[str] = None
    guest_email: Optional[str] = None
    guest_phone: Optional[str] = None
    confirmation_code: Optional[str] = None
    special_requests: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    confirmed_at: Optional[datetime] = None
    seated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    canceled_at: Optional[datetime] = None
    canceled_reason: Optional[str] = None
    no_show_at: Optional[datetime] = None
    voucher_id: Optional[int] = None
    voucher_discount_amount: Optional[float] = None
    prepayment_required: bool = False
    prepayment_amount: Optional[float] = None
    upsell_packages: Optional[List["UpsellPackageRead"]] = None  # Wird manuell gesetzt

    class Config:
        from_attributes = True


# Areas
class AreaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class AreaUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)


class AreaRead(BaseModel):
    id: int
    restaurant_id: int
    name: str

    class Config:
        from_attributes = True


# Obstacles
class ObstacleCreate(BaseModel):
    area_id: Optional[int] = None
    type: str = Field(min_length=1, max_length=32)
    name: Optional[str] = Field(None, max_length=120)
    x: int
    y: int
    width: int
    height: int
    rotation: Optional[int] = None
    blocking: bool = True
    color: Optional[str] = Field(None, max_length=16)
    notes: Optional[str] = None


class ObstacleUpdate(BaseModel):
    area_id: Optional[int] = None
    type: Optional[str] = Field(None, min_length=1, max_length=32)
    name: Optional[str] = Field(None, max_length=120)
    x: Optional[int] = None
    y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    rotation: Optional[int] = None
    blocking: Optional[bool] = None
    color: Optional[str] = Field(None, max_length=16)
    notes: Optional[str] = None


class ObstacleRead(BaseModel):
    id: int
    restaurant_id: int
    area_id: Optional[int] = None
    type: str
    name: Optional[str] = None
    x: int
    y: int
    width: int
    height: int
    rotation: Optional[int] = None
    blocking: bool
    color: Optional[str] = None
    notes: Optional[str] = None

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
    reason: Optional[str] = None


class BlockUpdate(BaseModel):
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    reason: Optional[str] = None


class BlockRead(BaseModel):
    id: int
    restaurant_id: int
    start_at: datetime
    end_at: datetime
    reason: Optional[str] = None
    created_by_user_id: Optional[int] = None

    class Config:
        from_attributes = True


# Waitlist
class WaitlistCreate(BaseModel):
    guest_id: Optional[int] = None
    party_size: int = Field(gt=0)
    desired_from: Optional[datetime] = None
    desired_to: Optional[datetime] = None
    status: str = "waiting"
    priority: Optional[int] = None
    notes: Optional[str] = None


class WaitlistUpdate(BaseModel):
    guest_id: Optional[int] = None
    party_size: Optional[int] = Field(None, gt=0)
    desired_from: Optional[datetime] = None
    desired_to: Optional[datetime] = None
    status: Optional[str] = None
    priority: Optional[int] = None
    notes: Optional[str] = None
    notified_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None


class WaitlistRead(BaseModel):
    id: int
    restaurant_id: int
    guest_id: Optional[int] = None
    party_size: int
    desired_from: Optional[datetime] = None
    desired_to: Optional[datetime] = None
    status: str
    priority: Optional[int] = None
    notified_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at_utc: datetime

    class Config:
        from_attributes = True


# Messages
class MessageCreate(BaseModel):
    reservation_id: Optional[int] = None
    guest_id: Optional[int] = None
    direction: str
    channel: str
    address: str
    body: str
    status: str = "queued"


class MessageUpdate(BaseModel):
    status: Optional[str] = None
    body: Optional[str] = None
    channel: Optional[str] = None
    address: Optional[str] = None


class MessageRead(BaseModel):
    id: int
    restaurant_id: int
    reservation_id: Optional[int] = None
    guest_id: Optional[int] = None
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
    entity_id: Optional[int] = None
    action: str = Field(min_length=1, max_length=32)
    description: Optional[str] = None
    details: Optional[dict[str, Any]] = None


class AuditLogRead(BaseModel):
    id: int
    restaurant_id: int
    user_id: Optional[int] = None
    entity_type: str
    entity_id: Optional[int] = None
    action: str
    description: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    ip_address: Optional[str] = None
    created_at_utc: datetime

    class Config:
        from_attributes = True


# Order Schemas
class OrderItemCreate(BaseModel):
    item_name: str = Field(min_length=1, max_length=200)
    item_description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    quantity: int = Field(gt=0, default=1)
    unit_price: float = Field(ge=0)  # Preis inkl. MwSt.
    tax_rate: Optional[float] = Field(None, ge=0, le=1)  # MwSt-Satz
    notes: Optional[str] = None
    sort_order: Optional[int] = 0


class OrderItemUpdate(BaseModel):
    item_name: Optional[str] = Field(None, min_length=1, max_length=200)
    item_description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    quantity: Optional[int] = Field(None, gt=0)
    unit_price: Optional[float] = Field(None, ge=0)  # Preis inkl. MwSt.
    tax_rate: Optional[float] = Field(None, ge=0, le=1)  # MwSt-Satz
    status: Optional[str] = None
    notes: Optional[str] = None
    sort_order: Optional[int] = None


class OrderItemRead(Timestamped):
    id: int
    order_id: int
    menu_item_id: Optional[int] = None
    item_name: str
    item_description: Optional[str] = None
    category: Optional[str] = None
    quantity: int
    unit_price: float  # Preis inkl. MwSt.
    total_price: float  # Gesamtpreis inkl. MwSt.
    tax_rate: float  # MwSt-Satz
    status: str
    notes: Optional[str] = None
    sort_order: Optional[int] = None

    class Config:
        from_attributes = True


class SplitPayment(BaseModel):
    method: str
    amount: float
    tip_amount: Optional[float] = None
    is_paid: Optional[bool] = False
    item_ids: Optional[List[int]] = None


class OrderCreate(BaseModel):
    table_id: Optional[int] = None
    guest_id: Optional[int] = None
    reservation_id: Optional[int] = None
    party_size: Optional[int] = Field(None, gt=0)
    notes: Optional[str] = None
    special_requests: Optional[str] = None
    split_payments: Optional[List[SplitPayment]] = None
    items: Optional[List[OrderItemCreate]] = None


class OrderUpdate(BaseModel):
    table_id: Optional[int] = None
    guest_id: Optional[int] = None
    reservation_id: Optional[int] = None
    status: Optional[str] = None
    party_size: Optional[int] = Field(None, gt=0)
    subtotal: Optional[float] = Field(None, ge=0)
    tax_amount_7: Optional[float] = Field(None, ge=0)
    tax_amount_19: Optional[float] = Field(None, ge=0)
    tax_amount: Optional[float] = Field(None, ge=0)  # Gesamt-MwSt. (für Kompatibilität)
    discount_amount: Optional[float] = Field(None, ge=0)
    discount_percentage: Optional[float] = Field(None, ge=0, le=100)
    tip_amount: Optional[float] = Field(None, ge=0)
    total: Optional[float] = Field(None, ge=0)
    payment_method: Optional[str] = Field(None, max_length=32)
    payment_status: Optional[str] = None
    split_payments: Optional[List[SplitPayment]] = None
    notes: Optional[str] = None
    special_requests: Optional[str] = None
    closed_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None


class OrderRead(Timestamped):
    id: int
    restaurant_id: int
    table_id: Optional[int] = None
    guest_id: Optional[int] = None
    reservation_id: Optional[int] = None
    order_number: Optional[str] = None
    status: str
    party_size: Optional[int] = None
    subtotal: float  # Zwischensumme inkl. MwSt.
    tax_amount_7: float  # MwSt. bei 7%
    tax_amount_19: float  # MwSt. bei 19%
    tax_amount: float  # Gesamt-MwSt. (für Kompatibilität)
    discount_amount: float
    discount_percentage: Optional[float] = None
    tip_amount: Optional[float] = None
    total: float
    payment_method: Optional[str] = None
    payment_status: str
    split_payments: Optional[List[SplitPayment]] = None
    notes: Optional[str] = None
    special_requests: Optional[str] = None
    opened_at: datetime
    closed_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    created_by_user_id: Optional[int] = None

    class Config:
        from_attributes = True


class OrderWithItems(OrderRead):
    items: List[OrderItemRead] = []


# Menu Schemas
class MenuCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = None
    sort_order: Optional[int] = 0
    is_active: bool = True


class MenuCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class MenuCategoryRead(Timestamped):
    id: int
    restaurant_id: int
    name: str
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: bool

    class Config:
        from_attributes = True


class MenuItemCreate(BaseModel):
    category_id: Optional[int] = None
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    price: float = Field(ge=0)  # Preis inkl. MwSt.
    tax_rate: float = Field(default=0.19, ge=0, le=1)  # MwSt-Satz (0.19 = 19%, 0.07 = 7%)
    is_available: bool = True
    sort_order: Optional[int] = 0
    allergens: Optional[List[str]] = None
    modifiers: Optional[List[dict]] = None


class MenuItemUpdate(BaseModel):
    category_id: Optional[int] = None
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    price: Optional[float] = Field(None, ge=0)  # Preis inkl. MwSt.
    tax_rate: Optional[float] = Field(None, ge=0, le=1)  # MwSt-Satz
    is_available: Optional[bool] = None
    sort_order: Optional[int] = None
    allergens: Optional[List[str]] = None
    modifiers: Optional[List[dict]] = None


class MenuItemRead(Timestamped):
    id: int
    restaurant_id: int
    category_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    price: float  # Preis inkl. MwSt.
    tax_rate: float  # MwSt-Satz (0.19 = 19%, 0.07 = 7%)
    is_available: bool
    sort_order: Optional[int] = None
    allergens: Optional[List[str]] = None
    modifiers: Optional[List[dict]] = None

    class Config:
        from_attributes = True


# ============================================================================
# Voucher Schemas
# ============================================================================

class VoucherCreate(BaseModel):
    restaurant_id: int
    code: str = Field(min_length=3, max_length=64)
    name: Optional[str] = None
    description: Optional[str] = None
    type: str = Field(pattern="^(fixed|percentage)$")  # fixed oder percentage
    value: float = Field(gt=0)
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    max_uses: Optional[int] = Field(None, gt=0)
    min_order_value: Optional[float] = Field(None, ge=0)
    is_active: bool = True


class VoucherUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = Field(None, pattern="^(fixed|percentage)$")
    value: Optional[float] = Field(None, gt=0)
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    max_uses: Optional[int] = Field(None, gt=0)
    min_order_value: Optional[float] = Field(None, ge=0)
    is_active: Optional[bool] = None


class VoucherRead(Timestamped):
    id: int
    restaurant_id: int
    code: str
    name: Optional[str] = None
    description: Optional[str] = None
    type: str
    value: float
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    max_uses: Optional[int] = None
    used_count: int
    min_order_value: Optional[float] = None
    is_active: bool

    class Config:
        from_attributes = True


class VoucherValidateRequest(BaseModel):
    code: str
    restaurant_id: int
    reservation_amount: Optional[float] = Field(None, ge=0)  # Betrag der Reservierung für Validierung


class VoucherValidateResponse(BaseModel):
    valid: bool
    voucher: Optional[VoucherRead] = None
    discount_amount: Optional[float] = None  # Berechneter Rabattbetrag
    message: str


# ============================================================================
# Upsell Package Schemas
# ============================================================================

class UpsellPackageCreate(BaseModel):
    restaurant_id: int
    name: str = Field(min_length=1, max_length=240)
    description: Optional[str] = None
    price: float = Field(gt=0)
    is_active: bool = True
    available_from_date: Optional[date] = None
    available_until_date: Optional[date] = None
    min_party_size: Optional[int] = Field(None, gt=0)
    max_party_size: Optional[int] = Field(None, gt=0)
    available_times: Optional[dict] = None  # {"monday": ["18:00", "19:00"], ...}
    available_weekdays: Optional[List[int]] = None  # [0,1,2,3,4,5,6] für Mo-So
    image_url: Optional[str] = None
    display_order: int = 0


class UpsellPackageUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=240)
    description: Optional[str] = None
    price: Optional[float] = Field(None, gt=0)
    is_active: Optional[bool] = None
    available_from_date: Optional[date] = None
    available_until_date: Optional[date] = None
    min_party_size: Optional[int] = Field(None, gt=0)
    max_party_size: Optional[int] = Field(None, gt=0)
    available_times: Optional[dict] = None
    available_weekdays: Optional[List[int]] = None
    image_url: Optional[str] = None
    display_order: Optional[int] = None


class UpsellPackageRead(Timestamped):
    id: int
    restaurant_id: int
    name: str
    description: Optional[str] = None
    price: float
    is_active: bool
    available_from_date: Optional[date] = None
    available_until_date: Optional[date] = None
    min_party_size: Optional[int] = None
    max_party_size: Optional[int] = None
    available_times: Optional[dict] = None
    available_weekdays: Optional[List[int]] = None
    image_url: Optional[str] = None
    display_order: int

    class Config:
        from_attributes = True


class UpsellPackageAvailabilityRequest(BaseModel):
    restaurant_id: int
    date: date
    time: str  # HH:MM Format
    party_size: int = Field(gt=0)


class UpsellPackageAvailabilityResponse(BaseModel):
    packages: List[UpsellPackageRead]


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
    payment_id: Optional[str] = None
    transaction_id: Optional[str] = None
    status: str
    payment_data: Optional[dict] = None
    completed_at_utc: Optional[datetime] = None

    class Config:
        from_attributes = True

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, Float, func, Date, JSON
from datetime import datetime, timezone
from app.database import Base
from sqlalchemy import UniqueConstraint


class Activity_Logs(Base):
    __tablename__ = 'activity_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String, nullable=False)
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ip_address = Column(String(45))


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), index=True, nullable=False)
    revoked_at = Column(DateTime(timezone=True), index=True, nullable=True)
    rotated_from_id = Column(Integer, nullable=True)
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    operator_number = Column(String(4), nullable=False, unique=True, index=True)  # 4-stellige Bedienernummer
    pin_hash = Column(String(255), nullable=False)  # 6-8 stelliger PIN (gehasht)
    nfc_tag_id = Column(String(64), nullable=True, unique=True, index=True)  # NFC-Tag-ID für Transponder-Login
    first_name = Column(String(120), nullable=False)
    last_name = Column(String(120), nullable=False)
    role = Column(String(20), nullable=False, default="mitarbeiter")  # servecta, restaurantinhaber, schichtleiter, mitarbeiter
    is_active = Column(Boolean, nullable=False, default=True)
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    last_login_at_utc = Column(DateTime(timezone=True), nullable=True, index=True)


class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    settings = Column(JSON, nullable=False, default=dict)
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=True, index=True)
    action = Column(String(32), nullable=False)
    description = Column(Text, nullable=True)
    details = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class Restaurant(Base):
    __tablename__ = 'restaurants'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    slug = Column(String(100), nullable=True, unique=True, index=True)  # URL-freundlicher Name für öffentliche Buchungen
    address = Column(String(500), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    
    # Public Booking Einstellungen
    public_booking_enabled = Column(Boolean, nullable=False, default=False)
    booking_lead_time_hours = Column(Integer, nullable=False, default=2)  # Mindestvorlaufzeit für Buchungen
    booking_max_party_size = Column(Integer, nullable=False, default=12)  # Maximale Personenanzahl
    booking_default_duration = Column(Integer, nullable=False, default=120)  # Standard-Reservierungsdauer in Minuten
    opening_hours = Column(JSON, nullable=True)  # {"monday": {"open": "11:00", "close": "23:00"}, ...}
    
    # SumUp Integration
    sumup_enabled = Column(Boolean, nullable=False, default=False)
    sumup_merchant_code = Column(String(32), nullable=True)  # SumUp Merchant Code (z.B. "MH4H92C7")
    sumup_api_key = Column(String(255), nullable=True)  # SumUp API Key (verschlüsselt gespeichert)
    sumup_default_reader_id = Column(String(64), nullable=True)  # Standard Reader ID für dieses Restaurant
    
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Table(Base):
    __tablename__ = 'tables'

    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    area_id = Column(Integer, ForeignKey("areas.id", ondelete="SET NULL"), nullable=True, index=True)
    number = Column(String(50), nullable=False)
    capacity = Column(Integer, nullable=False)
    shape = Column(String(20), nullable=True, default="rectangle")  # rectangle, circle, square
    position_x = Column(Float, nullable=True)  # Position für Drag-and-Drop (Standardaufstellung)
    position_y = Column(Float, nullable=True)  # Position für Drag-and-Drop (Standardaufstellung)
    width = Column(Float, nullable=True, default=120.0)  # Breite in Pixel
    height = Column(Float, nullable=True, default=120.0)  # Höhe in Pixel
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)
    # Erweiterte Felder (aus Reference)
    is_joinable = Column(Boolean, nullable=False, default=False)
    join_group_id = Column(Integer, nullable=True)
    is_outdoor = Column(Boolean, nullable=False, default=False)
    rotation = Column(Integer, nullable=True)
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class TableDayConfig(Base):
    """Tages-spezifische Konfiguration für Tische. Überschreibt Standardwerte aus Table."""
    __tablename__ = 'table_day_configs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    table_id = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=True, index=True)
    date = Column(Date, nullable=False, index=True)
    
    # Flag: Ist dieser Tisch für diesen Tag versteckt (gelöscht)?
    is_hidden = Column(Boolean, nullable=False, default=False)
    
    # Flag: Ist dies ein temporärer Tisch, der nur für diesen Tag existiert?
    is_temporary = Column(Boolean, nullable=False, default=False)
    
    # Felder die tages-spezifisch überschrieben werden können (auch für temporäre Tische)
    number = Column(String(50), nullable=True)  # Für temporäre Tische erforderlich
    capacity = Column(Integer, nullable=True)  # Für temporäre Tische erforderlich
    shape = Column(String(20), nullable=True)
    position_x = Column(Float, nullable=True)
    position_y = Column(Float, nullable=True)
    width = Column(Float, nullable=True)
    height = Column(Float, nullable=True)
    is_active = Column(Boolean, nullable=True)
    color = Column(String(16), nullable=True)
    join_group_id = Column(Integer, nullable=True)
    is_joinable = Column(Boolean, nullable=True)
    rotation = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    __table_args__ = (UniqueConstraint('restaurant_id', 'table_id', 'date', name='uq_table_day_config'),)


class Guest(Base):
    __tablename__ = 'guests'

    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    first_name = Column(String(120), nullable=False)
    last_name = Column(String(120), nullable=False)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(32), nullable=True, index=True)
    language = Column(String(10), nullable=True)
    birthday = Column(DateTime(timezone=True), nullable=True)
    company = Column(String(200), nullable=True)
    type = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Reservation(Base):
    __tablename__ = 'reservations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    guest_id = Column(Integer, ForeignKey("guests.id", ondelete="SET NULL"), nullable=True, index=True)
    table_id = Column(Integer, ForeignKey("tables.id", ondelete="SET NULL"), nullable=True, index=True)

    start_at = Column(DateTime(timezone=True), nullable=False, index=True)
    end_at = Column(DateTime(timezone=True), nullable=False)
    party_size = Column(Integer, nullable=False)

    status = Column(String(32), nullable=False, default="pending")
    channel = Column(String(32), nullable=False, default="manual")

    guest_name = Column(String(240), nullable=True)
    guest_email = Column(String(255), nullable=True)
    guest_phone = Column(String(32), nullable=True)
    confirmation_code = Column(String(64), nullable=True, index=True)

    special_requests = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    seated_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    canceled_at = Column(DateTime(timezone=True), nullable=True)
    canceled_reason = Column(Text, nullable=True)
    no_show_at = Column(DateTime(timezone=True), nullable=True)
    tags = Column(JSON, default=list)
    
    # Voucher & Prepayment
    voucher_id = Column(Integer, ForeignKey("vouchers.id", ondelete="SET NULL"), nullable=True, index=True)
    voucher_discount_amount = Column(Float, nullable=True)  # Abgezogener Betrag durch Gutschein
    prepayment_required = Column(Boolean, nullable=False, default=False)  # Ist Vorauszahlung erforderlich?
    prepayment_amount = Column(Float, nullable=True)  # Betrag der Vorauszahlung

    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ReservationTable(Base):
    __tablename__ = "reservation_tables"
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="CASCADE"), primary_key=True)
    table_id = Column(Integer, ForeignKey("tables.id", ondelete="RESTRICT"), primary_key=True)
    start_at = Column(DateTime(timezone=True), nullable=False, index=True)
    end_at = Column(DateTime(timezone=True), nullable=False)


class ReservationTableDayConfig(Base):
    """Verknüpft Reservierungen mit temporären Tischen (TableDayConfig)."""
    __tablename__ = "reservation_table_day_configs"
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="CASCADE"), primary_key=True)
    table_day_config_id = Column(Integer, ForeignKey("table_day_configs.id", ondelete="CASCADE"), primary_key=True)
    start_at = Column(DateTime(timezone=True), nullable=False, index=True)
    end_at = Column(DateTime(timezone=True), nullable=False)


class Block(Base):
    __tablename__ = "blocks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    start_at = Column(DateTime(timezone=True), nullable=False)
    end_at = Column(DateTime(timezone=True), nullable=False)
    reason = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class BlockAssignment(Base):
    __tablename__ = "block_assignments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    block_id = Column(Integer, ForeignKey("blocks.id", ondelete="CASCADE"), nullable=False, index=True)
    table_id = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("block_id", "table_id", name="uq_block_assignment_table"),
    )


class Waitlist(Base):
    __tablename__ = "waitlist"
    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    guest_id = Column(Integer, ForeignKey("guests.id", ondelete="CASCADE"), nullable=True, index=True)
    party_size = Column(Integer, nullable=False)
    desired_from = Column(DateTime(timezone=True), nullable=True)
    desired_to = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(24), nullable=False, default="waiting")
    priority = Column(Integer, nullable=True)
    notified_at = Column(DateTime(timezone=True), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="SET NULL"), nullable=True, index=True)
    guest_id = Column(Integer, ForeignKey("guests.id", ondelete="SET NULL"), nullable=True, index=True)
    direction = Column(String(32), nullable=False)
    channel = Column(String(32), nullable=False)
    address = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="queued")
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Area(Base):
    __tablename__ = "areas"
    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    __table_args__ = (UniqueConstraint('restaurant_id', 'name', name='uq_area_restaurant_name'),)


class Obstacle(Base):
    __tablename__ = "obstacles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    area_id = Column(Integer, ForeignKey("areas.id", ondelete="SET NULL"), nullable=True, index=True)
    type = Column(String(32), nullable=False)
    name = Column(String(120), nullable=True)
    x = Column(Integer, nullable=False)
    y = Column(Integer, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    rotation = Column(Integer, nullable=True)
    blocking = Column(Boolean, nullable=False, default=True)
    color = Column(String(16), nullable=True)
    notes = Column(Text, nullable=True)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    table_id = Column(Integer, ForeignKey("tables.id", ondelete="SET NULL"), nullable=True, index=True)
    guest_id = Column(Integer, ForeignKey("guests.id", ondelete="SET NULL"), nullable=True, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="SET NULL"), nullable=True, index=True)
    
    order_number = Column(String(64), nullable=True, unique=True, index=True)
    status = Column(String(32), nullable=False, default="open")  # open, sent_to_kitchen, in_preparation, ready, served, paid, canceled
    party_size = Column(Integer, nullable=True)
    
    subtotal = Column(Float, nullable=False, default=0.0)  # Zwischensumme inkl. MwSt.
    tax_amount_7 = Column(Float, nullable=False, default=0.0)  # MwSt. bei 7% Steuersatz
    tax_amount_19 = Column(Float, nullable=False, default=0.0)  # MwSt. bei 19% Steuersatz
    tax_amount = Column(Float, nullable=False, default=0.0)  # Gesamt-MwSt. (für Kompatibilität)
    discount_amount = Column(Float, nullable=False, default=0.0)
    discount_percentage = Column(Float, nullable=True)  # Optional: Rabatt in Prozent
    tip_amount = Column(Float, nullable=False, default=0.0)  # Trinkgeld
    total = Column(Float, nullable=False, default=0.0)
    
    payment_method = Column(String(32), nullable=True)  # cash, card, split, etc.
    payment_status = Column(String(32), nullable=False, default="unpaid")  # unpaid, partial, paid
    split_payments = Column(JSON, nullable=True)  # [{method: "cash", amount: 10.0}, {method: "card", amount: 20.0}]
    
    notes = Column(Text, nullable=True)
    special_requests = Column(Text, nullable=True)
    
    opened_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id", ondelete="SET NULL"), nullable=True, index=True)
    
    item_name = Column(String(200), nullable=False)
    item_description = Column(Text, nullable=True)
    category = Column(String(100), nullable=True)
    
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Float, nullable=False)  # Preis inkl. MwSt.
    total_price = Column(Float, nullable=False)  # quantity * unit_price (inkl. MwSt.)
    tax_rate = Column(Float, nullable=False, default=0.19)  # MwSt-Satz zum Zeitpunkt der Bestellung (0.19 = 19%, 0.07 = 7%)
    
    status = Column(String(32), nullable=False, default="pending")  # pending, sent, in_preparation, ready, served, canceled
    notes = Column(Text, nullable=True)
    
    sort_order = Column(Integer, nullable=True, default=0)  # Für Sortierung in der UI
    
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class MenuCategory(Base):
    __tablename__ = "menu_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, nullable=True, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("menu_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)  # Preis inkl. MwSt.
    tax_rate = Column(Float, nullable=False, default=0.19)  # MwSt-Satz (0.19 = 19%, 0.07 = 7%)
    is_available = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=True, default=0)
    allergens = Column(JSON, nullable=True)  # ["gluten", "lactose", ...]
    modifiers = Column(JSON, nullable=True)  # [{name: "Größe", options: [{name: "Klein", price_diff: 0}, ...]}, ...]
    
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SumUpPayment(Base):
    """Speichert SumUp-Zahlungsinformationen für Bestellungen."""
    __tablename__ = "sumup_payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # SumUp IDs
    checkout_id = Column(String(128), nullable=True, index=True)  # SumUp Checkout ID
    client_transaction_id = Column(String(128), nullable=True, index=True)  # Client Transaction ID
    transaction_code = Column(String(64), nullable=True, index=True)  # SumUp Transaction Code (z.B. "TEENSK4W2K")
    transaction_id = Column(String(128), nullable=True, index=True)  # SumUp Transaction ID
    
    # Reader/Terminal Info
    reader_id = Column(String(64), nullable=True)  # Reader ID für Terminal-Zahlung
    
    # Payment Details
    amount = Column(Float, nullable=False)  # Zahlungsbetrag
    currency = Column(String(3), nullable=False, default="EUR")
    status = Column(String(32), nullable=False, default="pending")  # pending, processing, successful, failed, canceled
    
    # Webhook Data
    webhook_data = Column(JSON, nullable=True)  # Gespeicherte Webhook-Daten
    
    # Timestamps
    initiated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Voucher(Base):
    """Gutscheine für Reservierungen."""
    __tablename__ = 'vouchers'

    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    
    code = Column(String(64), nullable=False, unique=True, index=True)  # Gutschein-Code
    name = Column(String(240), nullable=True)  # Name des Gutscheins (z.B. "Geschenkgutschein")
    description = Column(Text, nullable=True)  # Beschreibung
    
    # Gutschein-Typ: "fixed" (fester Betrag) oder "percentage" (Prozent)
    type = Column(String(32), nullable=False, default="fixed")  # fixed, percentage
    value = Column(Float, nullable=False)  # Betrag in EUR oder Prozent (0-100)
    
    # Gültigkeit
    valid_from = Column(Date, nullable=True)  # Ab wann gültig
    valid_until = Column(Date, nullable=True)  # Bis wann gültig
    
    # Nutzung
    max_uses = Column(Integer, nullable=True)  # Maximale Anzahl Nutzungen (None = unbegrenzt)
    used_count = Column(Integer, nullable=False, default=0)  # Anzahl bereits genutzter Gutscheine
    
    # Mindestbestellwert
    min_order_value = Column(Float, nullable=True)  # Mindestbestellwert für Gutschein-Nutzung
    
    # Status
    is_active = Column(Boolean, nullable=False, default=True)
    
    # Metadaten
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class VoucherUsage(Base):
    """Nutzung eines Gutscheins."""
    __tablename__ = 'voucher_usage'

    id = Column(Integer, primary_key=True, autoincrement=True)
    voucher_id = Column(Integer, ForeignKey("vouchers.id", ondelete="CASCADE"), nullable=False, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="SET NULL"), nullable=True, index=True)
    
    used_by_email = Column(String(255), nullable=True)  # E-Mail des Nutzers
    discount_amount = Column(Float, nullable=False)  # Abgezogener Betrag
    
    used_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UpsellPackage(Base):
    """Upsell-Pakete für Reservierungen (Menü-Upgrades, Getränkepakete, etc.)."""
    __tablename__ = 'upsell_packages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    
    name = Column(String(240), nullable=False)  # Name des Pakets
    description = Column(Text, nullable=True)  # Beschreibung
    price = Column(Float, nullable=False)  # Preis in EUR
    
    # Verfügbarkeit
    is_active = Column(Boolean, nullable=False, default=True)
    available_from_date = Column(Date, nullable=True)  # Ab wann verfügbar
    available_until_date = Column(Date, nullable=True)  # Bis wann verfügbar
    
    # Bedingungen
    min_party_size = Column(Integer, nullable=True)  # Mindest-Gästeanzahl
    max_party_size = Column(Integer, nullable=True)  # Maximale Gästeanzahl
    
    # Verfügbare Zeiten (JSON: {"monday": ["18:00", "19:00"], ...})
    available_times = Column(JSON, nullable=True)
    
    # Verfügbare Wochentage (JSON: [0,1,2,3,4,5,6] für Mo-So)
    available_weekdays = Column(JSON, nullable=True)
    
    # Metadaten
    image_url = Column(String(512), nullable=True)  # Bild-URL
    display_order = Column(Integer, nullable=False, default=0)  # Reihenfolge der Anzeige
    
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ReservationPrepayment(Base):
    """Vorauszahlungen für Reservierungen."""
    __tablename__ = 'reservation_prepayments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    
    amount = Column(Float, nullable=False)  # Betrag in EUR
    currency = Column(String(3), nullable=False, default="EUR")
    
    # Payment-Provider (z.B. "sumup", "stripe")
    payment_provider = Column(String(32), nullable=False)
    payment_id = Column(String(128), nullable=True)  # Externe Payment-ID
    transaction_id = Column(String(128), nullable=True)  # Transaction-ID
    
    # Status: pending, processing, completed, failed, refunded
    status = Column(String(32), nullable=False, default="pending")
    
    # Metadaten
    payment_data = Column(JSON, nullable=True)  # Zusätzliche Payment-Daten
    
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at_utc = Column(DateTime(timezone=True), nullable=True)


class ReservationUpsellPackage(Base):
    """Verknüpfung zwischen Reservierungen und Upsell-Paketen."""
    __tablename__ = 'reservation_upsell_packages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True)
    upsell_package_id = Column(Integer, ForeignKey("upsell_packages.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Preis zum Zeitpunkt der Reservierung (falls sich Preis später ändert)
    price_at_time = Column(Float, nullable=False)
    
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    __table_args__ = (UniqueConstraint('reservation_id', 'upsell_package_id', name='uq_reservation_upsell_package'),)

"""Import all models so SQLAlchemy resolves ForeignKey references."""

from app.models.audit import AuditLog, PlatformAuditLog  # noqa: F401
from app.models.block import Block, BlockAssignment  # noqa: F401
from app.models.device import Device  # noqa: F401
from app.models.guest_favorite import GuestFavorite  # noqa: F401
from app.models.menu import MenuCategory, MenuItem  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.reservation import Guest, Reservation, ReservationInvite  # noqa: F401
from app.models.restaurant import Area, Obstacle, Restaurant, Table  # noqa: F401
from app.models.review import Review  # noqa: F401
from app.models.table_config import (  # noqa: F401
    ReservationTable,
    ReservationTableDayConfig,
    TableDayConfig,
)
from app.models.user import GuestProfile, RefreshToken, User  # noqa: F401
from app.models.user_settings import UserSettings  # noqa: F401
from app.models.waitlist import Message, Waitlist  # noqa: F401

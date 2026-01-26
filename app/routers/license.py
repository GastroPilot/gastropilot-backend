"""
License Router - Endpoint zum Abrufen der aktuellen Feature-Flags
"""

from fastapi import APIRouter, Depends

from app.database.models import User
from app.dependencies import get_current_user
from app.services.license_service import ALL_MODULES, license_service

router = APIRouter(prefix="/license", tags=["license"])


@router.get("/features")
async def get_features(
    current_user: User = Depends(get_current_user),
):
    """
    Gibt die aktuellen Feature-Flags zurück.

    Verfügbare Module:
    - reservations_module: Reservierungsmodul (Tischplan, Kalender, Warteliste, Gäste-Verwaltung)
    - orders_module: Bestellungs-/Menümodul (Bestellsystem, Menüverwaltung, Statistiken)
    - web_reservation_module: Web-Reservierungsformular für die Website
    - whatsapp_bot_module: WhatsApp-Reservierungsbot
    - phone_bot_module: Telefon-Reservierungsbot
    """
    await license_service.ensure_initialized()
    return license_service.get_features()


@router.get("/info")
async def get_license_info(
    current_user: User = Depends(get_current_user),
):
    """
    Gibt erweiterte Lizenz-Informationen zurück inkl. Paket und Kundeninfo.
    """
    await license_service.ensure_initialized()
    return {
        "features": license_service.get_features(),
        "package": license_service.get_package(),
        "customer": license_service.get_customer_info(),
        "available_modules": ALL_MODULES,
    }

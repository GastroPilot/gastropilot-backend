from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.models.user import User
from app.services.license_service import license_service

router = APIRouter(prefix="/license", tags=["license"])


@router.get("/features")
async def get_features(current_user: User = Depends(get_current_user)):
    return license_service.get_features()


@router.get("/info")
async def get_info(current_user: User = Depends(get_current_user)):
    return {
        "package": license_service.get_package(),
        "features": license_service.get_features(),
        "customer": license_service.get_customer_info(),
    }

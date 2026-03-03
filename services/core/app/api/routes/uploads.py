"""Image upload endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile

from app.core.deps import get_current_user
from app.services.upload_service import upload_image

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("/menu-item-image")
async def upload_menu_item_image(
    file: UploadFile,
    request: Request,
    current_user=Depends(get_current_user),
):
    """Upload a menu item image."""
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")

    file_data = await file.read()
    content_type = file.content_type or "image/jpeg"

    try:
        url = await upload_image(file_data, content_type, "menu-items", str(tenant_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"url": url}


@router.post("/restaurant-image")
async def upload_restaurant_image(
    file: UploadFile,
    request: Request,
    current_user=Depends(get_current_user),
):
    """Upload a restaurant image."""
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")

    file_data = await file.read()
    content_type = file.content_type or "image/jpeg"

    try:
        url = await upload_image(
            file_data, content_type, "restaurants", str(tenant_id)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"url": url}

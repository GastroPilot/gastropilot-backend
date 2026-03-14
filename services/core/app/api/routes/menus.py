from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    get_current_user,
    get_db,
    require_manager_or_above,
    require_staff_or_above,
)
from app.models.menu import MenuCategory, MenuItem
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.menu import (
    MenuCategoryCreate,
    MenuCategoryResponse,
    MenuCategoryUpdate,
    MenuItemCreate,
    MenuItemResponse,
    MenuItemUpdate,
)

router = APIRouter(prefix="/menus", tags=["menus"])


async def _resolve_tenant_context_for_menu(
    request: Request,
    current_user: User,
    db: AsyncSession,
    requested_tenant_id: UUID | None,
) -> UUID:
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id
    if effective_tenant_id:
        if requested_tenant_id and requested_tenant_id != effective_tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Requested restaurant_id does not match tenant context",
            )
        return effective_tenant_id

    if current_user.role != "platform_admin":
        raise HTTPException(status_code=403, detail="User has no tenant context")

    if requested_tenant_id:
        restaurant_result = await db.execute(
            select(Restaurant.id).where(Restaurant.id == requested_tenant_id)
        )
        if restaurant_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Restaurant not found")
        return requested_tenant_id

    raise HTTPException(
        status_code=400,
        detail=(
            "Tenant context required (token has no tenant and no restaurant tenant "
            "could be resolved)"
        ),
    )


# ---------------------------------------------------------------------------
# Kategorien
# ---------------------------------------------------------------------------


@router.get("/categories", response_model=list[MenuCategoryResponse])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(
        select(MenuCategory).order_by(MenuCategory.sort_order, MenuCategory.name)
    )
    return result.scalars().all()


@router.post(
    "/categories", response_model=MenuCategoryResponse, status_code=status.HTTP_201_CREATED
)
async def create_category(
    request: Request,
    body: MenuCategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_menu(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=body.restaurant_id,
    )
    category = MenuCategory(
        tenant_id=effective_tenant_id,
        **body.model_dump(exclude={"restaurant_id"}),
    )
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


@router.patch("/categories/{category_id}", response_model=MenuCategoryResponse)
async def update_category(
    category_id: UUID,
    body: MenuCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    result = await db.execute(select(MenuCategory).where(MenuCategory.id == category_id))
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=404, detail="Kategorie nicht gefunden")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(category, field, value)

    await db.commit()
    await db.refresh(category)
    return category


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    result = await db.execute(select(MenuCategory).where(MenuCategory.id == category_id))
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=404, detail="Kategorie nicht gefunden")
    await db.delete(category)
    await db.commit()


# ---------------------------------------------------------------------------
# Gerichte
# ---------------------------------------------------------------------------


@router.get("/items", response_model=list[MenuItemResponse])
async def list_items(
    category_id: UUID | None = None,
    available_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    query = select(MenuItem)
    if category_id:
        query = query.where(MenuItem.category_id == category_id)
    if available_only:
        query = query.where(MenuItem.is_available.is_(True))
    query = query.order_by(MenuItem.sort_order, MenuItem.name)

    result = await db.execute(query)
    return result.scalars().all()


@router.post("/items", response_model=MenuItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    request: Request,
    body: MenuItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    effective_tenant_id = await _resolve_tenant_context_for_menu(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=body.restaurant_id,
    )
    if body.category_id:
        category_result = await db.execute(
            select(MenuCategory).where(MenuCategory.id == body.category_id)
        )
        category = category_result.scalar_one_or_none()
        if not category:
            raise HTTPException(status_code=404, detail="Kategorie nicht gefunden")
        if category.tenant_id != effective_tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Kategorie gehört nicht zum Tenant-Kontext",
            )
    # Only pass fields that exist on the MenuItem model
    valid_fields = {c.key for c in MenuItem.__table__.columns} - {
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
    }
    data = {k: v for k, v in body.model_dump().items() if k in valid_fields}
    item = MenuItem(
        tenant_id=effective_tenant_id,
        **data,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.get("/items/{item_id}", response_model=MenuItemResponse)
async def get_item(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(select(MenuItem).where(MenuItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Gericht nicht gefunden")
    return item


@router.patch("/items/{item_id}", response_model=MenuItemResponse)
async def update_item(
    item_id: UUID,
    body: MenuItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    result = await db.execute(select(MenuItem).where(MenuItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Gericht nicht gefunden")

    valid_fields = {c.key for c in MenuItem.__table__.columns} - {
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
    }
    for field, value in body.model_dump(exclude_none=True).items():
        if field in valid_fields:
            setattr(item, field, value)

    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    result = await db.execute(select(MenuItem).where(MenuItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Gericht nicht gefunden")
    await db.delete(item)
    await db.commit()

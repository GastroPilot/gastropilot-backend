from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import MenuCategory, MenuItem, Restaurant, User
from app.dependencies import (
    get_current_user,
    get_session,
    require_orders_module,
    require_schichtleiter_role,
)
from app.schemas import (
    MenuCategoryCreate,
    MenuCategoryRead,
    MenuCategoryUpdate,
    MenuItemCreate,
    MenuItemRead,
    MenuItemUpdate,
)

router = APIRouter(prefix="/restaurants/{restaurant_id}/menu", tags=["menu"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def _get_menu_item_or_404(
    menu_item_id: int, restaurant_id: int, session: AsyncSession
) -> MenuItem:
    menu_item = await session.get(MenuItem, menu_item_id)
    if not menu_item or menu_item.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu item not found")
    return menu_item


async def _get_menu_category_or_404(
    category_id: int, restaurant_id: int, session: AsyncSession
) -> MenuCategory:
    category = await session.get(MenuCategory, category_id)
    if not category or category.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu category not found")
    return category


# Menu Categories


@router.post(
    "/categories",
    response_model=MenuCategoryRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_orders_module)],
)
async def create_category(
    restaurant_id: int,
    category_data: MenuCategoryCreate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Erstellt eine neue Menü-Kategorie (Schichtleiter oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)

    category = MenuCategory(restaurant_id=restaurant_id, **category_data.model_dump())

    try:
        session.add(category)
        await session.commit()
        await session.refresh(category)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category conflict")

    return category


@router.get("/categories", response_model=list[MenuCategoryRead])
async def list_categories(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(get_current_user),
):
    """Listet alle Menü-Kategorien eines Restaurants."""
    await _get_restaurant_or_404(restaurant_id, session)

    result = await session.execute(
        select(MenuCategory)
        .where(MenuCategory.restaurant_id == restaurant_id)
        .order_by(MenuCategory.sort_order, MenuCategory.name)
    )
    return result.scalars().all()


@router.get("/categories/{category_id}", response_model=MenuCategoryRead)
async def get_category(
    restaurant_id: int,
    category_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(get_current_user),
):
    """Holt eine einzelne Menü-Kategorie."""
    await _get_restaurant_or_404(restaurant_id, session)
    return await _get_menu_category_or_404(category_id, restaurant_id, session)


@router.patch("/categories/{category_id}", response_model=MenuCategoryRead)
async def update_category(
    restaurant_id: int,
    category_id: int,
    category_data: MenuCategoryUpdate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Aktualisiert eine Menü-Kategorie (Schichtleiter oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)
    category = await _get_menu_category_or_404(category_id, restaurant_id, session)

    update_data = category_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(category, field, value)

    try:
        await session.commit()
        await session.refresh(category)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category conflict")

    return category


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    restaurant_id: int,
    category_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Löscht eine Menü-Kategorie (Schichtleiter oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)
    category = await _get_menu_category_or_404(category_id, restaurant_id, session)

    try:
        await session.delete(category)
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise


# Menu Items


@router.post("/items", response_model=MenuItemRead, status_code=status.HTTP_201_CREATED)
async def create_menu_item(
    restaurant_id: int,
    item_data: MenuItemCreate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Erstellt einen neuen Menü-Artikel (Schichtleiter oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)

    if item_data.category_id:
        await _get_menu_category_or_404(item_data.category_id, restaurant_id, session)

    menu_item = MenuItem(restaurant_id=restaurant_id, **item_data.model_dump())

    try:
        session.add(menu_item)
        await session.commit()
        await session.refresh(menu_item)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Menu item conflict")

    return menu_item


@router.get("/items", response_model=list[MenuItemRead])
async def list_menu_items(
    restaurant_id: int,
    category_id: int | None = None,
    available_only: bool = False,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(get_current_user),
):
    """Listet alle Menü-Artikel eines Restaurants."""
    await _get_restaurant_or_404(restaurant_id, session)

    query = select(MenuItem).where(MenuItem.restaurant_id == restaurant_id)

    if category_id:
        query = query.where(MenuItem.category_id == category_id)

    if available_only:
        query = query.where(MenuItem.is_available == True)

    query = query.order_by(MenuItem.sort_order, MenuItem.name)

    result = await session.execute(query)
    return result.scalars().all()


@router.get("/items/{item_id}", response_model=MenuItemRead)
async def get_menu_item(
    restaurant_id: int,
    item_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(get_current_user),
):
    """Holt einen einzelnen Menü-Artikel."""
    await _get_restaurant_or_404(restaurant_id, session)
    return await _get_menu_item_or_404(item_id, restaurant_id, session)


@router.patch("/items/{item_id}", response_model=MenuItemRead)
async def update_menu_item(
    restaurant_id: int,
    item_id: int,
    item_data: MenuItemUpdate,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Aktualisiert einen Menü-Artikel (Schichtleiter oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)
    menu_item = await _get_menu_item_or_404(item_id, restaurant_id, session)

    update_data = item_data.model_dump(exclude_unset=True)

    if "category_id" in update_data and update_data["category_id"]:
        await _get_menu_category_or_404(update_data["category_id"], restaurant_id, session)

    for field, value in update_data.items():
        setattr(menu_item, field, value)

    try:
        await session.commit()
        await session.refresh(menu_item)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Menu item conflict")

    return menu_item


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_menu_item(
    restaurant_id: int,
    item_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_schichtleiter_role),
):
    """Löscht einen Menü-Artikel (Schichtleiter oder höher)."""
    await _get_restaurant_or_404(restaurant_id, session)
    menu_item = await _get_menu_item_or_404(item_id, restaurant_id, session)

    try:
        await session.delete(menu_item)
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise

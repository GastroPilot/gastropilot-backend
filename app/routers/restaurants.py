from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Restaurant
from app.dependencies import get_current_user, get_session, require_servecta_role
from app.schemas import RestaurantCreate, RestaurantRead, RestaurantUpdate

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


@router.get("/public/name")
async def get_restaurant_name_public(session: AsyncSession = Depends(get_session)):
    """Gibt den Namen des ersten Restaurants zurück (öffentlich, ohne Authentifizierung)."""
    result = await session.execute(select(Restaurant).limit(1))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        return {"name": "GastroPilot"}
    return {"name": restaurant.name}


@router.post("/", response_model=RestaurantRead, status_code=status.HTTP_201_CREATED)
async def create_restaurant(
    restaurant_data: RestaurantCreate,
    session: AsyncSession = Depends(get_session),
    current_user=Depends(require_servecta_role),
):
    """Erstellt ein neues Restaurant (nur Servecta)."""
    restaurant = Restaurant(**restaurant_data.model_dump())
    try:
        session.add(restaurant)
        await session.commit()
        await session.refresh(restaurant)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Restaurant already exists"
        )
    return restaurant


@router.get("/", response_model=list[RestaurantRead])
async def list_restaurants(
    session: AsyncSession = Depends(get_session), current_user=Depends(get_current_user)
):
    """Listet alle Restaurants."""
    result = await session.execute(select(Restaurant))
    return result.scalars().all()


@router.get("/{restaurant_id}", response_model=RestaurantRead)
async def get_restaurant(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    """Holt ein einzelnes Restaurant."""
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


@router.patch("/{restaurant_id}", response_model=RestaurantRead)
async def update_restaurant(
    restaurant_id: int,
    restaurant_data: RestaurantUpdate,
    session: AsyncSession = Depends(get_session),
    current_user=Depends(require_servecta_role),
):
    """Aktualisiert ein Restaurant (nur Servecta)."""
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    update_data = restaurant_data.model_dump(exclude_unset=True)

    # SumUp API Key und Merchant Code werden serverseitig verwaltet und nicht überschrieben
    # Diese Felder werden ignoriert, wenn sie im Update-Request enthalten sind
    update_data.pop("sumup_api_key", None)
    update_data.pop("sumup_merchant_code", None)

    for field, value in update_data.items():
        setattr(restaurant, field, value)

    try:
        await session.commit()
        await session.refresh(restaurant)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Restaurant already exists"
        )
    return restaurant


@router.delete("/{restaurant_id}", status_code=status.HTTP_200_OK)
async def delete_restaurant(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    current_user=Depends(require_servecta_role),
):
    """Löscht ein Restaurant (nur Servecta)."""
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    try:
        await session.delete(restaurant)
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise
    return {"message": "deleted"}

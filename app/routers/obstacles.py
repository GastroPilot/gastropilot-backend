from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Area, Obstacle, Restaurant, User
from app.dependencies import get_current_user, get_session, require_mitarbeiter_role
from app.schemas import ObstacleCreate, ObstacleRead, ObstacleUpdate

router = APIRouter(prefix="/restaurants/{restaurant_id}/obstacles", tags=["obstacles"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def _get_obstacle_or_404(
    obstacle_id: int, restaurant_id: int, session: AsyncSession
) -> Obstacle:
    ob = await session.get(Obstacle, obstacle_id)
    if not ob or ob.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Obstacle not found")
    return ob


async def _validate_area(area_id: int | None, restaurant_id: int, session: AsyncSession) -> None:
    if area_id is None:
        return
    area = await session.get(Area, area_id)
    if not area or area.restaurant_id != restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Area not found")


@router.post("/", response_model=ObstacleRead, status_code=status.HTTP_201_CREATED)
async def create_obstacle(
    restaurant_id: int,
    body: ObstacleCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    await _validate_area(body.area_id, restaurant_id, session)
    ob = Obstacle(
        restaurant_id=restaurant_id,
        area_id=body.area_id,
        type=body.type,
        name=body.name,
        x=body.x,
        y=body.y,
        width=body.width,
        height=body.height,
        rotation=body.rotation,
        blocking=body.blocking if body.blocking is not None else True,
        color=body.color,
        notes=body.notes,
    )
    try:
        session.add(ob)
        await session.commit()
        await session.refresh(ob)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Obstacle conflict")
    return ob


@router.get("/", response_model=list[ObstacleRead])
async def list_obstacles(
    restaurant_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    await _get_restaurant_or_404(restaurant_id, session)
    res = await session.execute(select(Obstacle).where(Obstacle.restaurant_id == restaurant_id))
    return res.scalars().all()


@router.patch("/{obstacle_id}", response_model=ObstacleRead)
async def update_obstacle(
    restaurant_id: int,
    obstacle_id: int,
    body: ObstacleUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    ob = await _get_obstacle_or_404(obstacle_id, restaurant_id, session)
    data = body.model_dump(exclude_unset=True)
    if "area_id" in data:
        await _validate_area(data.get("area_id"), restaurant_id, session)
    for field, value in data.items():
        setattr(ob, field, value)
    try:
        await session.commit()
        await session.refresh(ob)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Obstacle conflict")
    return ob


@router.delete("/{obstacle_id}", status_code=status.HTTP_200_OK)
async def delete_obstacle(
    restaurant_id: int,
    obstacle_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_mitarbeiter_role),
):
    await _get_restaurant_or_404(restaurant_id, session)
    ob = await _get_obstacle_or_404(obstacle_id, restaurant_id, session)
    try:
        await session.delete(ob)
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        raise
    return {"message": "deleted"}

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_manager_or_above, require_owner_or_above
from app.models.restaurant import Area, Obstacle, Restaurant, Table

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TenantSettings(BaseModel):
    """Strukturierte Tenant-Einstellungen. Neue Keys werden automatisch in settings JSONB gespeichert."""

    # Allgemein
    timezone: str = "Europe/Berlin"
    currency: str = "EUR"
    language: str = "de"
    logo_url: str | None = None
    primary_color: str | None = None
    # Buchung
    public_booking_enabled: bool = False
    booking_lead_time_hours: int = Field(default=2, ge=0, le=168)
    booking_max_party_size: int = Field(default=12, ge=1, le=100)
    booking_default_duration_minutes: int = Field(default=120, ge=15, le=480)
    opening_hours: dict | None = None
    # Bestellungen
    order_number_prefix: str = "B"
    receipt_footer: str | None = None
    tax_rate: float = Field(default=19.0, ge=0, le=100)
    # Benachrichtigungen
    notify_new_reservation_email: bool = True
    notify_new_order_push: bool = True

    model_config = {"extra": "allow"}


class TenantSettingsUpdate(BaseModel):
    """Partial update – nur übergebene Felder werden aktualisiert."""

    timezone: str | None = None
    currency: str | None = None
    language: str | None = None
    logo_url: str | None = None
    primary_color: str | None = None
    public_booking_enabled: bool | None = None
    booking_lead_time_hours: int | None = Field(default=None, ge=0, le=168)
    booking_max_party_size: int | None = Field(default=None, ge=1, le=100)
    booking_default_duration_minutes: int | None = Field(default=None, ge=15, le=480)
    opening_hours: dict | None = None
    order_number_prefix: str | None = None
    receipt_footer: str | None = None
    tax_rate: float | None = Field(default=None, ge=0, le=100)
    notify_new_reservation_email: bool | None = None
    notify_new_order_push: bool | None = None

    model_config = {"extra": "allow"}


class RestaurantResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    description: str | None = None
    settings: dict

    class Config:
        from_attributes = True


class RestaurantUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    description: str | None = None


# ---------------------------------------------------------------------------
# Hilfsfunktion: Restaurant-Spalten + JSONB zu TenantSettings zusammenführen
# ---------------------------------------------------------------------------


def _build_settings(restaurant: Restaurant) -> dict[str, Any]:
    """Mergt strukturierte DB-Spalten mit dem freien settings-JSONB."""
    base: dict[str, Any] = {
        "timezone": "Europe/Berlin",
        "currency": "EUR",
        "language": "de",
        "logo_url": None,
        "primary_color": None,
        "public_booking_enabled": restaurant.public_booking_enabled,
        "booking_lead_time_hours": restaurant.booking_lead_time_hours,
        "booking_max_party_size": restaurant.booking_max_party_size,
        "booking_default_duration_minutes": restaurant.booking_default_duration,
        "opening_hours": restaurant.opening_hours,
        "order_number_prefix": "B",
        "receipt_footer": None,
        "tax_rate": 19.0,
        "notify_new_reservation_email": True,
        "notify_new_order_push": True,
    }
    # JSONB-Werte überschreiben Defaults
    if restaurant.settings:
        base.update(restaurant.settings)
    return base


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/public/name")
async def get_public_name(slug: str | None = None, session: AsyncSession = Depends(get_db)):
    """Öffentlicher Endpoint – liefert den Restaurantnamen für die Login-Seite.
    Optional: ?slug=restaurant-slug gibt den Namen des spezifischen Restaurants zurück."""
    if slug:
        result = await session.execute(select(Restaurant).where(Restaurant.slug == slug))
    else:
        result = await session.execute(select(Restaurant).limit(1))
    restaurant = result.scalar_one_or_none()
    return {
        "name": restaurant.name if restaurant else "GastroPilot",
        "found": restaurant is not None,
    }


@router.get("", response_model=list[RestaurantResponse])
async def list_restaurants(
    request: Request,
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    is_impersonating = getattr(request.state, "is_impersonating", False)
    effective_tenant_id = getattr(request.state, "tenant_id", None)

    if current_user.role == "platform_admin" and not is_impersonating:
        # Reiner Admin-Kontext: alle Tenants zurückgeben
        result = await session.execute(select(Restaurant))
    else:
        # Normal-User ODER impersonierender Admin: effektiver Tenant aus Middleware
        tenant_id = effective_tenant_id or current_user.tenant_id
        if not tenant_id:
            return []
        result = await session.execute(select(Restaurant).where(Restaurant.id == tenant_id))
    restaurants = result.scalars().all()
    return [
        RestaurantResponse(
            id=r.id,
            name=r.name,
            slug=r.slug,
            address=r.address,
            phone=r.phone,
            email=r.email,
            description=r.description,
            settings=_build_settings(r),
        )
        for r in restaurants
    ]


@router.get("/{restaurant_id}", response_model=RestaurantResponse)
async def get_restaurant(
    restaurant_id: uuid.UUID,
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    if current_user.role != "platform_admin" and current_user.tenant_id != restaurant_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return RestaurantResponse(
        id=restaurant.id,
        name=restaurant.name,
        slug=restaurant.slug,
        address=restaurant.address,
        phone=restaurant.phone,
        email=restaurant.email,
        description=restaurant.description,
        settings=_build_settings(restaurant),
    )


@router.patch("/{restaurant_id}", response_model=RestaurantResponse)
async def update_restaurant(
    restaurant_id: uuid.UUID,
    data: RestaurantUpdate,
    current_user=Depends(require_manager_or_above),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    if current_user.role != "platform_admin" and current_user.tenant_id != restaurant_id:
        raise HTTPException(status_code=403, detail="Access denied")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(restaurant, field, value)

    await session.commit()
    await session.refresh(restaurant)
    return RestaurantResponse(
        id=restaurant.id,
        name=restaurant.name,
        slug=restaurant.slug,
        address=restaurant.address,
        phone=restaurant.phone,
        email=restaurant.email,
        description=restaurant.description,
        settings=_build_settings(restaurant),
    )


# ---------------------------------------------------------------------------
# Tenant-Einstellungen
# ---------------------------------------------------------------------------


@router.get("/{restaurant_id}/settings", response_model=TenantSettings)
async def get_settings(
    restaurant_id: uuid.UUID,
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Gibt alle Tenant-Einstellungen zurück (strukturierte Spalten + JSONB-Extras)."""
    result = await session.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    if current_user.role != "platform_admin" and current_user.tenant_id != restaurant_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return _build_settings(restaurant)


@router.patch("/{restaurant_id}/settings", response_model=TenantSettings)
async def update_settings(
    restaurant_id: uuid.UUID,
    data: TenantSettingsUpdate,
    current_user=Depends(require_manager_or_above),
    session: AsyncSession = Depends(get_db),
):
    """Aktualisiert Tenant-Einstellungen. Bekannte Felder → DB-Spalten, der Rest → settings JSONB."""
    result = await session.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    if current_user.role != "platform_admin" and current_user.tenant_id != restaurant_id:
        raise HTTPException(status_code=403, detail="Access denied")

    patch = data.model_dump(exclude_none=True)

    # Strukturierte Spalten direkt setzen
    column_map = {
        "public_booking_enabled": "public_booking_enabled",
        "booking_lead_time_hours": "booking_lead_time_hours",
        "booking_max_party_size": "booking_max_party_size",
        "booking_default_duration_minutes": "booking_default_duration",
        "opening_hours": "opening_hours",
    }
    for settings_key, col_name in column_map.items():
        if settings_key in patch:
            setattr(restaurant, col_name, patch.pop(settings_key))

    # Rest geht in den JSONB-settings-Block
    if patch:
        current_settings = dict(restaurant.settings or {})
        current_settings.update(patch)
        restaurant.settings = current_settings

    await session.commit()
    await session.refresh(restaurant)
    return _build_settings(restaurant)


# ---------------------------------------------------------------------------
# Tische, Bereiche, Hindernisse
# ---------------------------------------------------------------------------


@router.get("/{restaurant_id}/tables")
async def list_tables(
    restaurant_id: uuid.UUID,
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(Table).where(Table.tenant_id == restaurant_id, Table.is_active == True)
    )
    tables = result.scalars().all()
    return [_table_to_dict(t) for t in tables]


@router.get("/{restaurant_id}/tables/{table_id}")
async def get_table(
    restaurant_id: uuid.UUID,
    table_id: uuid.UUID,
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(Table).where(Table.id == table_id, Table.tenant_id == restaurant_id)
    )
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Table not found")
    return _table_to_dict(t)


def _table_to_dict(t: Table) -> dict:
    return {
        "id": str(t.id),
        "number": t.number,
        "capacity": t.capacity,
        "shape": t.shape,
        "position_x": t.position_x,
        "position_y": t.position_y,
        "width": t.width,
        "height": t.height,
        "is_active": t.is_active,
        "is_joinable": t.is_joinable,
        "is_outdoor": t.is_outdoor,
        "rotation": t.rotation,
        "area_id": str(t.area_id) if t.area_id else None,
        "notes": t.notes,
    }


@router.post("/{restaurant_id}/tables", status_code=201)
async def create_table(
    restaurant_id: uuid.UUID,
    body: dict,
    current_user=Depends(require_manager_or_above),
    session: AsyncSession = Depends(get_db),
):
    valid_fields = {c.key for c in Table.__table__.columns} - {
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
    }
    data = {k: v for k, v in body.items() if k in valid_fields}
    table = Table(tenant_id=restaurant_id, **data)
    session.add(table)
    await session.commit()
    await session.refresh(table)
    return _table_to_dict(table)


@router.patch("/{restaurant_id}/tables/{table_id}")
async def update_table(
    restaurant_id: uuid.UUID,
    table_id: uuid.UUID,
    body: dict,
    current_user=Depends(require_manager_or_above),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(Table).where(Table.id == table_id, Table.tenant_id == restaurant_id)
    )
    table = result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")
    valid_fields = {c.key for c in Table.__table__.columns} - {
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
    }
    for field, value in body.items():
        if field in valid_fields:
            setattr(table, field, value)
    await session.commit()
    await session.refresh(table)
    return _table_to_dict(table)


@router.delete("/{restaurant_id}/tables/{table_id}", status_code=204)
async def delete_table(
    restaurant_id: uuid.UUID,
    table_id: uuid.UUID,
    current_user=Depends(require_manager_or_above),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(Table).where(Table.id == table_id, Table.tenant_id == restaurant_id)
    )
    table = result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")
    await session.delete(table)
    await session.commit()


@router.get("/{restaurant_id}/areas")
async def list_areas(
    restaurant_id: uuid.UUID,
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Area).where(Area.tenant_id == restaurant_id))
    areas = result.scalars().all()
    return [{"id": str(a.id), "name": a.name} for a in areas]


@router.post("/{restaurant_id}/areas", status_code=201)
async def create_area(
    restaurant_id: uuid.UUID,
    body: dict,
    current_user=Depends(require_manager_or_above),
    session: AsyncSession = Depends(get_db),
):
    area = Area(tenant_id=restaurant_id, name=body["name"])
    session.add(area)
    await session.commit()
    await session.refresh(area)
    return {"id": str(area.id), "name": area.name}


@router.patch("/{restaurant_id}/areas/{area_id}")
async def update_area(
    restaurant_id: uuid.UUID,
    area_id: uuid.UUID,
    body: dict,
    current_user=Depends(require_manager_or_above),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(Area).where(Area.id == area_id, Area.tenant_id == restaurant_id)
    )
    area = result.scalar_one_or_none()
    if not area:
        raise HTTPException(status_code=404, detail="Area not found")
    if "name" in body:
        area.name = body["name"]
    await session.commit()
    await session.refresh(area)
    return {"id": str(area.id), "name": area.name}


@router.delete("/{restaurant_id}/areas/{area_id}", status_code=204)
async def delete_area(
    restaurant_id: uuid.UUID,
    area_id: uuid.UUID,
    current_user=Depends(require_manager_or_above),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(Area).where(Area.id == area_id, Area.tenant_id == restaurant_id)
    )
    area = result.scalar_one_or_none()
    if not area:
        raise HTTPException(status_code=404, detail="Area not found")
    await session.delete(area)
    await session.commit()


@router.get("/{restaurant_id}/obstacles")
async def list_obstacles(
    restaurant_id: uuid.UUID,
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Obstacle).where(Obstacle.tenant_id == restaurant_id))
    obstacles = result.scalars().all()
    return [
        {
            "id": str(o.id),
            "type": o.type,
            "name": o.name,
            "x": o.x,
            "y": o.y,
            "width": o.width,
            "height": o.height,
            "rotation": o.rotation,
            "blocking": o.blocking,
            "color": o.color,
            "area_id": str(o.area_id) if o.area_id else None,
        }
        for o in obstacles
    ]


def _obstacle_to_dict(o: Obstacle) -> dict:
    return {
        "id": str(o.id),
        "type": o.type,
        "name": o.name,
        "x": o.x,
        "y": o.y,
        "width": o.width,
        "height": o.height,
        "rotation": o.rotation,
        "blocking": o.blocking,
        "color": o.color,
        "area_id": str(o.area_id) if o.area_id else None,
    }


@router.post("/{restaurant_id}/obstacles", status_code=201)
async def create_obstacle(
    restaurant_id: uuid.UUID,
    body: dict,
    current_user=Depends(require_manager_or_above),
    session: AsyncSession = Depends(get_db),
):
    valid_fields = {c.key for c in Obstacle.__table__.columns} - {
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
    }
    data = {k: v for k, v in body.items() if k in valid_fields}
    obstacle = Obstacle(tenant_id=restaurant_id, **data)
    session.add(obstacle)
    await session.commit()
    await session.refresh(obstacle)
    return _obstacle_to_dict(obstacle)


@router.patch("/{restaurant_id}/obstacles/{obstacle_id}")
async def update_obstacle(
    restaurant_id: uuid.UUID,
    obstacle_id: uuid.UUID,
    body: dict,
    current_user=Depends(require_manager_or_above),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(Obstacle).where(Obstacle.id == obstacle_id, Obstacle.tenant_id == restaurant_id)
    )
    obstacle = result.scalar_one_or_none()
    if not obstacle:
        raise HTTPException(status_code=404, detail="Obstacle not found")
    valid_fields = {c.key for c in Obstacle.__table__.columns} - {
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
    }
    for field, value in body.items():
        if field in valid_fields:
            setattr(obstacle, field, value)
    await session.commit()
    await session.refresh(obstacle)
    return _obstacle_to_dict(obstacle)


@router.delete("/{restaurant_id}/obstacles/{obstacle_id}", status_code=204)
async def delete_obstacle(
    restaurant_id: uuid.UUID,
    obstacle_id: uuid.UUID,
    current_user=Depends(require_manager_or_above),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(Obstacle).where(Obstacle.id == obstacle_id, Obstacle.tenant_id == restaurant_id)
    )
    obstacle = result.scalar_one_or_none()
    if not obstacle:
        raise HTTPException(status_code=404, detail="Obstacle not found")
    await session.delete(obstacle)
    await session.commit()


@router.get("/{restaurant_id}/audit-logs/")
async def list_audit_logs(
    restaurant_id: uuid.UUID,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    user_id: str | None = None,
    limit: int = 25,
    offset: int = 0,
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    from sqlalchemy import and_, desc, func

    from app.models.audit import AuditLog

    # Zugriffsprüfung: nur eigener Tenant oder platform_admin
    if current_user.role != "platform_admin" and str(current_user.tenant_id) != str(restaurant_id):
        raise HTTPException(status_code=403, detail="Zugriff verweigert")

    filters = [AuditLog.tenant_id == restaurant_id]
    if entity_type:
        filters.append(AuditLog.entity_type == entity_type)
    if entity_id:
        try:
            filters.append(AuditLog.entity_id == uuid.UUID(entity_id))
        except ValueError:
            pass
    if action:
        filters.append(AuditLog.action == action)
    if user_id:
        try:
            filters.append(AuditLog.user_id == uuid.UUID(user_id))
        except ValueError:
            pass

    total_result = await session.execute(
        select(func.count()).select_from(AuditLog).where(and_(*filters))
    )
    total = total_result.scalar() or 0

    result = await session.execute(
        select(AuditLog)
        .where(and_(*filters))
        .order_by(desc(AuditLog.created_at))
        .limit(limit)
        .offset(offset)
    )
    logs = result.scalars().all()

    return {
        "results": [
            {
                "id": str(log.id),
                "restaurant_id": str(log.tenant_id),
                "user_id": str(log.user_id) if log.user_id else None,
                "entity_type": log.entity_type,
                "entity_id": str(log.entity_id) if log.entity_id else None,
                "action": log.action,
                "description": log.description,
                "details": log.details,
                "ip_address": log.ip_address,
                "created_at_utc": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

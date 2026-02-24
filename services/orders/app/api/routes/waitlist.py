from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_staff_or_above
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/waitlist", tags=["waitlist"])


# ---------------------------------------------------------------------------
# Pydantic-Schemas (lokal, kein separates schemas/-Modul nötig)
# ---------------------------------------------------------------------------


class WaitlistEntryCreate(BaseModel):
    guest_name: str
    party_size: int
    phone: str | None = None
    notes: str | None = None
    estimated_wait_minutes: int | None = None


class WaitlistEntryUpdate(BaseModel):
    status: str | None = None
    table_id: UUID | None = None
    estimated_wait_minutes: int | None = None
    notes: str | None = None


class WaitlistEntryResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    guest_name: str
    party_size: int
    phone: str | None = None
    notes: str | None = None
    status: str
    estimated_wait_minutes: int | None = None
    table_id: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# In-Memory-Warteliste (Redis-backed für Produktion)
# ---------------------------------------------------------------------------

import json

from app.services.cache_service import get_redis

WAITLIST_TTL = 86400  # 24 Stunden


async def _get_waitlist(tenant_id: UUID) -> list[dict]:
    r = get_redis()
    raw = await r.get(f"waitlist:{tenant_id}")
    if raw:
        return json.loads(raw)
    return []


async def _save_waitlist(tenant_id: UUID, entries: list[dict]) -> None:
    r = get_redis()
    await r.setex(f"waitlist:{tenant_id}", WAITLIST_TTL, json.dumps(entries, default=str))


# ---------------------------------------------------------------------------
# Endpunkte
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[WaitlistEntryResponse])
async def list_waitlist(
    current_user: User = Depends(require_staff_or_above),
):
    entries = await _get_waitlist(current_user.tenant_id)
    # Nur aktive Einträge zurückgeben
    active = [e for e in entries if e.get("status") in ("waiting", "notified")]
    return active


@router.post("/", response_model=WaitlistEntryResponse, status_code=status.HTTP_201_CREATED)
async def add_to_waitlist(
    body: WaitlistEntryCreate,
    current_user: User = Depends(require_staff_or_above),
):
    import uuid

    entry = {
        "id": str(uuid.uuid4()),
        "tenant_id": str(current_user.tenant_id),
        "guest_name": body.guest_name,
        "party_size": body.party_size,
        "phone": body.phone,
        "notes": body.notes,
        "status": "waiting",
        "estimated_wait_minutes": body.estimated_wait_minutes,
        "table_id": None,
        "created_at": datetime.now(UTC).isoformat(),
    }

    entries = await _get_waitlist(current_user.tenant_id)
    entries.append(entry)
    await _save_waitlist(current_user.tenant_id, entries)

    logger.info(
        "Warteliste: %s (%d Personen) hinzugefügt für Tenant %s",
        body.guest_name,
        body.party_size,
        current_user.tenant_id,
    )
    return entry


@router.patch("/{entry_id}", response_model=WaitlistEntryResponse)
async def update_waitlist_entry(
    entry_id: UUID,
    body: WaitlistEntryUpdate,
    current_user: User = Depends(require_staff_or_above),
):
    entries = await _get_waitlist(current_user.tenant_id)
    entry = next((e for e in entries if e["id"] == str(entry_id)), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Wartelisten-Eintrag nicht gefunden")

    if body.status is not None:
        entry["status"] = body.status
    if body.table_id is not None:
        entry["table_id"] = str(body.table_id)
    if body.estimated_wait_minutes is not None:
        entry["estimated_wait_minutes"] = body.estimated_wait_minutes
    if body.notes is not None:
        entry["notes"] = body.notes

    await _save_waitlist(current_user.tenant_id, entries)
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_waitlist(
    entry_id: UUID,
    current_user: User = Depends(require_staff_or_above),
):
    entries = await _get_waitlist(current_user.tenant_id)
    original_len = len(entries)
    entries = [e for e in entries if e["id"] != str(entry_id)]

    if len(entries) == original_len:
        raise HTTPException(status_code=404, detail="Wartelisten-Eintrag nicht gefunden")

    await _save_waitlist(current_user.tenant_id, entries)

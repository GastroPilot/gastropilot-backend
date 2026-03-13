"""Seating suggestion endpoint with block/reservation awareness."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.engines.seating_solver import (
    Block,
    ExistingReservation,
    SeatingRequest,
    Table,
    solve_seating,
)

router = APIRouter(prefix="/ai/seating", tags=["ai-seating"])


class TableInput(BaseModel):
    id: str
    capacity: int
    is_outdoor: bool = False
    is_joinable: bool = False
    area: str | None = None
    min_capacity: int = 1


class BlockInput(BaseModel):
    table_id: str
    start: datetime
    end: datetime
    reason: str = ""


class ReservationInput(BaseModel):
    table_id: str
    start: datetime
    end: datetime
    party_size: int
    status: str = "confirmed"


class SeatingInput(BaseModel):
    party_size: int | None = None
    available_tables: list[TableInput] = []
    existing_reservations: list[ReservationInput] = []
    blocks: list[BlockInput] = []
    preferences: dict | None = None
    requires_outdoor: bool = False
    prefers_outdoor: bool = False
    preferred_area: str | None = None
    reservation_start: datetime | None = None
    reservation_end: datetime | None = None
    context_hint: str | None = None
    # Smart Seating v2 fields
    guest_id: str | None = None
    tenant_id: str | None = None
    expected_revenue: float | None = None
    expected_duration_minutes: float | None = None
    ml_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    revpash_weight: float = Field(default=0.15, ge=0.0, le=1.0)


@router.post("/suggest")
async def suggest_seating(data: SeatingInput):
    if not data.available_tables or data.party_size is None:
        return {
            "suggestions": [],
            "ai_enabled": True,
            "message": "Keine Tisch-Daten übergeben",
            "total_scored": 0,
        }

    tables = [Table(**t.model_dump()) for t in data.available_tables]
    reservations = [ExistingReservation(**r.model_dump()) for r in data.existing_reservations]
    block_list = [Block(**b.model_dump()) for b in data.blocks]

    request = SeatingRequest(
        party_size=data.party_size,
        reservation_start=data.reservation_start,
        reservation_end=data.reservation_end,
        preferences=data.preferences,
        requires_outdoor=data.requires_outdoor,
        prefers_outdoor=data.prefers_outdoor,
        preferred_area=data.preferred_area,
        guest_id=data.guest_id,
        tenant_id=data.tenant_id,
        expected_revenue=data.expected_revenue,
        expected_duration_minutes=data.expected_duration_minutes,
    )
    result = solve_seating(
        request,
        tables,
        existing_assignments=reservations,
        blocks=block_list,
        ml_weight=data.ml_weight,
        revpash_weight=data.revpash_weight,
    )
    return {
        "suggestions": [
            {
                "table_id": s.table_id,
                "table_number": s.table_id,
                "confidence": s.score,
                "score": s.score,
                "reason": s.reason,
                "guest_name": None,
                "reservation_id": None,
                "is_join_group": s.is_join_group,
                "joined_table_ids": s.joined_table_ids,
                "ml_score": s.ml_score,
                "revpash_score": s.revpash_score,
            }
            for s in result.suggestions
        ],
        "ai_enabled": True,
        "message": None,
        "total_scored": result.total_scored,
    }

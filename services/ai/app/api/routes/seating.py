from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel
from app.engines.seating_solver import Table, SeatingRequest, solve_seating

router = APIRouter(prefix="/ai/seating", tags=["ai-seating"])


class TableInput(BaseModel):
    id: str
    capacity: int
    is_outdoor: bool = False
    is_joinable: bool = False
    area: str | None = None


class SeatingInput(BaseModel):
    party_size: int
    available_tables: list[TableInput]
    preferences: dict | None = None
    requires_outdoor: bool = False


@router.post("/suggest")
async def suggest_seating(data: SeatingInput):
    tables = [Table(**t.model_dump()) for t in data.available_tables]
    request = SeatingRequest(
        party_size=data.party_size,
        preferences=data.preferences,
        requires_outdoor=data.requires_outdoor,
    )
    result = solve_seating(request, tables)
    return {
        "suggestions": [
            {"table_id": s.table_id, "score": s.score, "reason": s.reason}
            for s in result.suggestions
        ],
        "total_scored": result.total_scored,
    }

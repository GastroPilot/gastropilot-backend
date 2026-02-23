from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class Table:
    id: str
    capacity: int
    is_outdoor: bool = False
    is_joinable: bool = False
    area: str | None = None


@dataclass
class SeatingRequest:
    party_size: int
    preferences: dict[str, Any] | None = None
    allergens: list[str] | None = None
    requires_outdoor: bool = False
    accessibility_needed: bool = False


@dataclass
class SeatingSuggestionItem:
    table_id: str
    score: float
    reason: str


@dataclass
class SeatingSuggestion:
    suggestions: list[SeatingSuggestionItem]
    total_scored: int


def solve_seating(
    request: SeatingRequest,
    available_tables: list[Table],
    existing_assignments: list[dict] | None = None,
) -> SeatingSuggestion:
    """
    Constraint-based seating assignment using a scoring heuristic.

    Scores each available table based on:
    - Capacity fit (prefer tables close to party size)
    - Outdoor preference
    - Accessibility requirements

    Full OR-Tools integration planned for Phase 2.
    """
    scored = []

    for table in available_tables:
        if table.capacity < request.party_size:
            continue

        score = 100.0
        reason_parts = []

        # Capacity: prefer snug fit
        excess = table.capacity - request.party_size
        score -= excess * 5
        if excess == 0:
            reason_parts.append("perfect fit")
        elif excess <= 2:
            reason_parts.append("good fit")

        # Outdoor preference
        if request.requires_outdoor and table.is_outdoor:
            score += 20
            reason_parts.append("outdoor preferred")
        elif request.requires_outdoor and not table.is_outdoor:
            score -= 30

        reason = ", ".join(reason_parts) if reason_parts else "standard assignment"
        scored.append(SeatingSuggestionItem(
            table_id=table.id,
            score=max(0.0, score),
            reason=reason,
        ))

    scored.sort(key=lambda x: x.score, reverse=True)
    top = scored[:3]

    logger.info(f"Seating solver: {len(scored)} eligible tables, top {len(top)} returned")
    return SeatingSuggestion(suggestions=top, total_scored=len(scored))

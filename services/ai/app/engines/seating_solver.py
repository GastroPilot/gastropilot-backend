"""Constraint-based seating solver with block/reservation awareness."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
    min_capacity: int = 1


@dataclass
class Block:
    table_id: str
    start: datetime
    end: datetime
    reason: str = ""


@dataclass
class ExistingReservation:
    table_id: str
    start: datetime
    end: datetime
    party_size: int
    status: str = "confirmed"


@dataclass
class SeatingRequest:
    party_size: int
    reservation_start: datetime | None = None
    reservation_end: datetime | None = None
    preferences: dict[str, Any] | None = None
    allergens: list[str] | None = None
    requires_outdoor: bool = False
    prefers_outdoor: bool = False
    accessibility_needed: bool = False
    preferred_area: str | None = None


@dataclass
class SeatingSuggestionItem:
    table_id: str
    score: float
    reason: str
    is_join_group: bool = False
    joined_table_ids: list[str] = field(default_factory=list)


@dataclass
class SeatingSuggestion:
    suggestions: list[SeatingSuggestionItem]
    total_scored: int


def _is_blocked(table_id: str, start: datetime, end: datetime, blocks: list[Block]) -> bool:
    for b in blocks:
        if b.table_id == table_id and b.start < end and b.end > start:
            return True
    return False


def _is_reserved(table_id: str, start: datetime, end: datetime, reservations: list[ExistingReservation]) -> bool:
    for r in reservations:
        if r.table_id == table_id and r.status in ("confirmed", "seated") and r.start < end and r.end > start:
            return True
    return False


def solve_seating(
    request: SeatingRequest,
    available_tables: list[Table],
    existing_assignments: list[ExistingReservation] | None = None,
    blocks: list[Block] | None = None,
) -> SeatingSuggestion:
    """
    Constraint-based seating assignment with full awareness of
    blocks, existing reservations, join-groups, and preferences.
    """
    existing_assignments = existing_assignments or []
    blocks = blocks or []
    prefs = request.preferences or {}

    scored: list[SeatingSuggestionItem] = []

    for table in available_tables:
        if table.capacity < request.party_size:
            continue
        if table.min_capacity > request.party_size:
            continue

        # Time-based conflict checks
        if request.reservation_start and request.reservation_end:
            if _is_blocked(table.id, request.reservation_start, request.reservation_end, blocks):
                continue
            if _is_reserved(table.id, request.reservation_start, request.reservation_end, existing_assignments):
                continue

        score = 100.0
        reason_parts: list[str] = []

        # Capacity fit — prefer smallest suitable table
        excess = table.capacity - request.party_size
        score -= excess * 5
        if excess == 0:
            reason_parts.append("perfect fit")
        elif excess <= 2:
            reason_parts.append("good fit")
        else:
            reason_parts.append(f"+{excess} extra seats")

        # Outdoor preference
        if request.requires_outdoor:
            if table.is_outdoor:
                score += 25
                reason_parts.append("outdoor required")
            else:
                continue  # Hard constraint
        elif request.prefers_outdoor:
            if table.is_outdoor:
                score += 15
                reason_parts.append("outdoor preferred")

        # Area preference
        if request.preferred_area and table.area:
            if table.area.lower() == request.preferred_area.lower():
                score += 10
                reason_parts.append(f"area: {table.area}")

        # Historical frequency bonus from preferences
        if prefs.get("frequent_table") == table.id:
            score += 8
            reason_parts.append("guest favorite")

        reason = ", ".join(reason_parts) if reason_parts else "standard assignment"
        scored.append(SeatingSuggestionItem(
            table_id=table.id,
            score=max(0.0, round(score, 1)),
            reason=reason,
        ))

    # Try join-groups if no single table fits
    if not scored and request.party_size > 1:
        joinable = [t for t in available_tables if t.is_joinable]
        # Simple greedy pair matching
        for i, t1 in enumerate(joinable):
            for t2 in joinable[i + 1:]:
                combined = t1.capacity + t2.capacity
                if combined >= request.party_size:
                    # Check conflicts for both
                    if request.reservation_start and request.reservation_end:
                        if _is_blocked(t1.id, request.reservation_start, request.reservation_end, blocks):
                            continue
                        if _is_blocked(t2.id, request.reservation_start, request.reservation_end, blocks):
                            continue
                        if _is_reserved(t1.id, request.reservation_start, request.reservation_end, existing_assignments):
                            continue
                        if _is_reserved(t2.id, request.reservation_start, request.reservation_end, existing_assignments):
                            continue

                    excess = combined - request.party_size
                    join_score = 70.0 - excess * 3
                    scored.append(SeatingSuggestionItem(
                        table_id=f"{t1.id}+{t2.id}",
                        score=max(0.0, round(join_score, 1)),
                        reason=f"joined tables ({t1.capacity}+{t2.capacity})",
                        is_join_group=True,
                        joined_table_ids=[t1.id, t2.id],
                    ))

    scored.sort(key=lambda x: x.score, reverse=True)
    top = scored[:5]

    logger.info("Seating solver: %d eligible, top %d returned for party of %d",
                len(scored), len(top), request.party_size)
    return SeatingSuggestion(suggestions=top, total_scored=len(scored))

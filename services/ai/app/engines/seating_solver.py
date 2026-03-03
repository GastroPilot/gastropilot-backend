"""Constraint-based seating solver with block/reservation awareness."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Default blending weights for ML and RevPASH scoring overlays.
# These can be overridden via the `ml_weight` and `revpash_weight` parameters.
DEFAULT_ML_WEIGHT = 0.3
DEFAULT_REVPASH_WEIGHT = 0.15


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
    guest_id: str | None = None
    tenant_id: str | None = None
    expected_revenue: float | None = None
    expected_duration_minutes: float | None = None


@dataclass
class SeatingSuggestionItem:
    table_id: str
    score: float
    reason: str
    is_join_group: bool = False
    joined_table_ids: list[str] = field(default_factory=list)
    ml_score: float | None = None
    revpash_score: float | None = None


@dataclass
class SeatingSuggestion:
    suggestions: list[SeatingSuggestionItem]
    total_scored: int


def _is_blocked(table_id: str, start: datetime, end: datetime, blocks: list[Block]) -> bool:
    for b in blocks:
        if b.table_id == table_id and b.start < end and b.end > start:
            return True
    return False


def _is_reserved(
    table_id: str, start: datetime, end: datetime, reservations: list[ExistingReservation]
) -> bool:
    for r in reservations:
        if (
            r.table_id == table_id
            and r.status in ("confirmed", "seated")
            and r.start < end
            and r.end > start
        ):
            return True
    return False


def _get_ml_scores(
    request: SeatingRequest,
    available_tables: list[Table],
) -> dict[str, float]:
    """Fetch ML preference scores if a trained model exists."""
    if not request.guest_id or not request.tenant_id:
        return {}

    try:
        from app.engines.seating_ml import get_engine

        engine = get_engine(request.tenant_id)
        tables_for_ml = [
            {"table_id": t.id, "area": t.area, "capacity": t.capacity}
            for t in available_tables
        ]
        context = {
            "party_size": request.party_size,
            "hour": request.reservation_start.hour if request.reservation_start else 12,
            "day_of_week": (
                request.reservation_start.weekday() if request.reservation_start else 0
            ),
        }
        predictions = engine.predict_preference(request.guest_id, tables_for_ml, context)
        return {p["table_id"]: p["ml_score"] for p in predictions}
    except Exception:
        logger.debug("ML scoring unavailable, skipping", exc_info=True)
        return {}


def _get_revpash_score(
    table: Table,
    expected_duration: float | None,
    expected_revenue: float | None,
    reservation_start: datetime | None,
) -> float:
    """Calculate RevPASH score bonus for a table assignment."""
    if not expected_duration or not expected_revenue:
        return 0.0

    try:
        from app.engines.revpash import score_table_revpash

        # Estimate remaining hours today (simple: assume service ends at 23:00)
        if reservation_start:
            hours_remaining = max(0.0, (23 - reservation_start.hour))
        else:
            hours_remaining = 4.0

        return score_table_revpash(
            table_id=table.id,
            capacity=table.capacity,
            expected_duration_minutes=expected_duration,
            expected_revenue=expected_revenue,
            hours_remaining_today=hours_remaining,
        )
    except Exception:
        logger.debug("RevPASH scoring unavailable, skipping", exc_info=True)
        return 0.0


def solve_seating(
    request: SeatingRequest,
    available_tables: list[Table],
    existing_assignments: list[ExistingReservation] | None = None,
    blocks: list[Block] | None = None,
    ml_weight: float = DEFAULT_ML_WEIGHT,
    revpash_weight: float = DEFAULT_REVPASH_WEIGHT,
) -> SeatingSuggestion:
    """
    Constraint-based seating assignment with full awareness of
    blocks, existing reservations, join-groups, and preferences.

    Optionally blends ML preference scores and RevPASH optimization
    with the rule-based score. Weights are configurable:
      final_score = (1 - ml_weight - revpash_weight) * rule_score
                  + ml_weight * ml_score
                  + revpash_weight * revpash_score
    """
    existing_assignments = existing_assignments or []
    blocks = blocks or []
    prefs = request.preferences or {}

    # Clamp weights so they sum to at most 1.0
    ml_w = max(0.0, min(1.0, ml_weight))
    rp_w = max(0.0, min(1.0, revpash_weight))
    if ml_w + rp_w > 1.0:
        total = ml_w + rp_w
        ml_w /= total
        rp_w /= total
    rule_w = 1.0 - ml_w - rp_w

    # Pre-fetch ML scores for all tables (single call)
    ml_scores = _get_ml_scores(request, available_tables)

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
            if _is_reserved(
                table.id, request.reservation_start, request.reservation_end, existing_assignments
            ):
                continue

        rule_score = 100.0
        reason_parts: list[str] = []

        # Capacity fit — prefer smallest suitable table
        excess = table.capacity - request.party_size
        rule_score -= excess * 5
        if excess == 0:
            reason_parts.append("perfect fit")
        elif excess <= 2:
            reason_parts.append("good fit")
        else:
            reason_parts.append(f"+{excess} extra seats")

        # Outdoor preference
        if request.requires_outdoor:
            if table.is_outdoor:
                rule_score += 25
                reason_parts.append("outdoor required")
            else:
                continue  # Hard constraint
        elif request.prefers_outdoor:
            if table.is_outdoor:
                rule_score += 15
                reason_parts.append("outdoor preferred")

        # Area preference
        if request.preferred_area and table.area:
            if table.area.lower() == request.preferred_area.lower():
                rule_score += 10
                reason_parts.append(f"area: {table.area}")

        # Historical frequency bonus from preferences
        if prefs.get("frequent_table") == table.id:
            rule_score += 8
            reason_parts.append("guest favorite")

        # ── ML overlay ────────────────────────────────────────────────
        table_ml_score = ml_scores.get(table.id)
        if table_ml_score is not None and table_ml_score > 60:
            reason_parts.append("ML preferred")

        # ── RevPASH overlay ───────────────────────────────────────────
        table_revpash_score = _get_revpash_score(
            table,
            request.expected_duration_minutes,
            request.expected_revenue,
            request.reservation_start,
        )
        if table_revpash_score > 15:
            reason_parts.append("high RevPASH")

        # ── Blend scores ──────────────────────────────────────────────
        ml_component = (table_ml_score or 50.0) * ml_w
        rp_component = (table_revpash_score / 30.0 * 100.0) * rp_w  # normalize 0-30 to 0-100
        rule_component = rule_score * rule_w
        final_score = rule_component + ml_component + rp_component

        reason = ", ".join(reason_parts) if reason_parts else "standard assignment"
        scored.append(
            SeatingSuggestionItem(
                table_id=table.id,
                score=max(0.0, round(final_score, 1)),
                reason=reason,
                ml_score=round(table_ml_score, 2) if table_ml_score is not None else None,
                revpash_score=round(table_revpash_score, 2) if table_revpash_score else None,
            )
        )

    # Try join-groups if no single table fits
    if not scored and request.party_size > 1:
        joinable = [t for t in available_tables if t.is_joinable]
        # Simple greedy pair matching
        for i, t1 in enumerate(joinable):
            for t2 in joinable[i + 1 :]:
                combined = t1.capacity + t2.capacity
                if combined >= request.party_size:
                    # Check conflicts for both
                    if request.reservation_start and request.reservation_end:
                        if _is_blocked(
                            t1.id, request.reservation_start, request.reservation_end, blocks
                        ):
                            continue
                        if _is_blocked(
                            t2.id, request.reservation_start, request.reservation_end, blocks
                        ):
                            continue
                        if _is_reserved(
                            t1.id,
                            request.reservation_start,
                            request.reservation_end,
                            existing_assignments,
                        ):
                            continue
                        if _is_reserved(
                            t2.id,
                            request.reservation_start,
                            request.reservation_end,
                            existing_assignments,
                        ):
                            continue

                    excess = combined - request.party_size
                    join_score = 70.0 - excess * 3
                    scored.append(
                        SeatingSuggestionItem(
                            table_id=f"{t1.id}+{t2.id}",
                            score=max(0.0, round(join_score, 1)),
                            reason=f"joined tables ({t1.capacity}+{t2.capacity})",
                            is_join_group=True,
                            joined_table_ids=[t1.id, t2.id],
                        )
                    )

    scored.sort(key=lambda x: x.score, reverse=True)
    top = scored[:5]

    logger.info(
        "Seating solver: %d eligible, top %d returned for party of %d",
        len(scored),
        len(top),
        request.party_size,
    )
    return SeatingSuggestion(suggestions=top, total_scored=len(scored))

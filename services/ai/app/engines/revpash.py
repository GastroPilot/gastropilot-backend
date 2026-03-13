"""Revenue per Available Seat Hour (RevPASH) optimization engine."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


def calculate_revpash(
    tables: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Calculate RevPASH metrics for each table.

    Args:
        tables: List of {table_id, capacity, hours_available}.
        history: List of seating records with
                 {table_id, revenue, duration_minutes, seated_at}.

    Returns:
        List of per-table RevPASH dicts sorted by score descending.
    """
    table_map = {t["table_id"]: t for t in tables}

    # Aggregate history per table
    table_revenue: dict[str, float] = defaultdict(float)
    table_durations: dict[str, list[float]] = defaultdict(list)

    for entry in history:
        tid = entry.get("table_id", "")
        revenue = entry.get("revenue") or 0.0
        duration = entry.get("duration_minutes") or 0.0

        table_revenue[tid] += revenue
        table_durations[tid].append(duration)

    results = []
    for tid, tinfo in table_map.items():
        capacity = tinfo.get("capacity", 1)
        hours_available = tinfo.get("hours_available", 1.0)

        total_rev = table_revenue.get(tid, 0.0)
        durations = table_durations.get(tid, [])
        total_occupied_hours = sum(durations) / 60.0 if durations else 0.0
        avg_turnover = sum(durations) / len(durations) if durations else 0.0

        # RevPASH = Total Revenue / (Available Seats * Available Hours)
        seat_hours = capacity * hours_available if hours_available > 0 else 1.0
        revpash = total_rev / seat_hours if seat_hours > 0 else 0.0

        # Occupancy rate
        occupancy = total_occupied_hours / hours_available if hours_available > 0 else 0.0

        results.append(
            {
                "table_id": tid,
                "capacity": capacity,
                "total_revenue": round(total_rev, 2),
                "total_hours_available": round(hours_available, 2),
                "total_hours_occupied": round(total_occupied_hours, 2),
                "revpash": round(revpash, 2),
                "occupancy_rate": round(min(1.0, occupancy), 4),
                "avg_turnover_minutes": round(avg_turnover, 1),
            }
        )

    # Normalize to 0-100 score
    max_revpash = max((r["revpash"] for r in results), default=1.0) or 1.0
    for r in results:
        r["score"] = round((r["revpash"] / max_revpash) * 100, 1)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def score_table_revpash(
    table_id: str,
    capacity: int,
    expected_duration_minutes: float,
    expected_revenue: float,
    hours_remaining_today: float = 4.0,
) -> float:
    """
    Score a single table assignment by its RevPASH potential.

    Used as an inline scoring factor during seating assignment.
    Returns a score from 0 to 30 (max bonus points).
    """
    if capacity <= 0 or hours_remaining_today <= 0:
        return 0.0

    # Estimated RevPASH contribution of this assignment
    duration_hours = expected_duration_minutes / 60.0
    if duration_hours <= 0:
        return 0.0

    # Revenue efficiency: revenue per seat-hour for this seating
    rev_per_seat_hour = expected_revenue / (capacity * duration_hours)

    # Turnover potential: shorter stays leave room for more seatings
    remaining_seatings = hours_remaining_today / duration_hours
    turnover_bonus = min(10.0, remaining_seatings * 2.0)

    # Capacity utilization penalty — empty seats are wasted RevPASH
    # (handled externally in solver, but we give a small nudge)
    efficiency = min(rev_per_seat_hour * 3.0, 20.0)

    score = efficiency + turnover_bonus
    return round(min(30.0, score), 1)

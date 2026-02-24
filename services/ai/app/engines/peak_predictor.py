"""Peak occupancy prediction with historical data support."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class PeakPrediction:
    hour: int
    predicted_occupancy: float  # 0.0 - 1.0
    confidence: float
    label: str  # "low" | "medium" | "high" | "peak"


# Baseline occupancy by hour (used when no historical data available)
_BASELINE: dict[int, float] = {
    0: 0.0,
    1: 0.0,
    2: 0.0,
    3: 0.0,
    4: 0.0,
    5: 0.0,
    6: 0.05,
    7: 0.1,
    8: 0.15,
    9: 0.2,
    10: 0.25,
    11: 0.4,
    12: 0.85,
    13: 0.9,
    14: 0.7,
    15: 0.4,
    16: 0.3,
    17: 0.35,
    18: 0.7,
    19: 0.95,
    20: 0.9,
    21: 0.75,
    22: 0.5,
    23: 0.2,
}

_WEEKEND_MULTIPLIER = 1.15
_FRIDAY_MULTIPLIER = 1.10


def _label_for_occupancy(occ: float) -> str:
    if occ < 0.3:
        return "low"
    if occ < 0.6:
        return "medium"
    if occ < 0.85:
        return "high"
    return "peak"


def predict_peak(
    date: datetime,
    tenant_id: str | None = None,
    historical_data: list[dict] | None = None,
    total_capacity: int | None = None,
) -> list[PeakPrediction]:
    """
    Predict hourly occupancy for a given date.

    If historical_data is provided (list of dicts with 'hour' and 'covers'),
    uses weighted average of historical + baseline. Otherwise pure baseline.

    Args:
        date: Target date.
        tenant_id: Optional tenant for logging.
        historical_data: Past reservation data [{hour: int, covers: int, date: str}, ...].
        total_capacity: Restaurant total seat capacity for normalization.
    """
    is_weekend = date.weekday() >= 5
    is_friday = date.weekday() == 4
    day_multiplier = (
        _WEEKEND_MULTIPLIER if is_weekend else (_FRIDAY_MULTIPLIER if is_friday else 1.0)
    )

    # Build historical hourly averages if data provided
    hist_avg: dict[int, float] = {}
    hist_weight = 0.0
    if historical_data and total_capacity and total_capacity > 0:
        hourly_sums: dict[int, list[float]] = defaultdict(list)
        for entry in historical_data:
            h = entry.get("hour")
            covers = entry.get("covers", 0)
            if h is not None:
                hourly_sums[int(h)].append(covers / total_capacity)

        for h, values in hourly_sums.items():
            hist_avg[h] = sum(values) / len(values) if values else 0.0

        # More data = higher confidence in historical
        data_points = len(historical_data)
        hist_weight = min(0.8, data_points / 100)  # caps at 80% historical weight

    predictions = []
    for hour in range(24):
        base = _BASELINE.get(hour, 0.0) * day_multiplier

        if hour in hist_avg and hist_weight > 0:
            blended = hist_avg[hour] * hist_weight + base * (1 - hist_weight)
            confidence = 0.5 + hist_weight * 0.4  # 0.5 to 0.82
        else:
            blended = base
            confidence = 0.4 if not historical_data else 0.5

        occ = min(1.0, max(0.0, blended))
        predictions.append(
            PeakPrediction(
                hour=hour,
                predicted_occupancy=round(occ, 2),
                confidence=round(confidence, 2),
                label=_label_for_occupancy(occ),
            )
        )

    return predictions

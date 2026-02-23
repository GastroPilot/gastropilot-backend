from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class PeakPrediction:
    hour: int
    predicted_occupancy: float  # 0.0 – 1.0
    confidence: float
    label: str  # "low" | "medium" | "high" | "peak"


# Baseline occupancy by hour (stub – Phase 2 will use scikit-learn + historical data)
_BASELINE: dict[int, float] = {
    0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0,
    6: 0.05, 7: 0.1, 8: 0.15, 9: 0.2, 10: 0.25,
    11: 0.4, 12: 0.85, 13: 0.9, 14: 0.7, 15: 0.4,
    16: 0.3, 17: 0.35, 18: 0.7, 19: 0.95, 20: 0.9,
    21: 0.75, 22: 0.5, 23: 0.2,
}

_WEEKEND_MULTIPLIER = 1.15


def predict_peak(
    date: datetime,
    tenant_id: str | None = None,
    historical_data: list[dict] | None = None,
) -> list[PeakPrediction]:
    """
    Predicts hourly occupancy for a given date.
    Currently uses a baseline heuristic.
    Phase 2: integrates historical data, weather, local events, scikit-learn.
    """
    is_weekend = date.weekday() >= 5
    multiplier = _WEEKEND_MULTIPLIER if is_weekend else 1.0

    predictions = []
    for hour, base in _BASELINE.items():
        occ = min(1.0, base * multiplier)
        confidence = 0.6 if not historical_data else 0.8

        if occ < 0.3:
            label = "low"
        elif occ < 0.6:
            label = "medium"
        elif occ < 0.85:
            label = "high"
        else:
            label = "peak"

        predictions.append(PeakPrediction(
            hour=hour,
            predicted_occupancy=round(occ, 2),
            confidence=confidence,
            label=label,
        ))

    return predictions

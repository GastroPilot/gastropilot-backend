"""Peak occupancy prediction endpoint."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from app.engines.peak_predictor import predict_peak

router = APIRouter(prefix="/ai/predictions", tags=["ai-predictions"])


@router.get("/peak")
async def get_peak_prediction(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    tenant_id: str | None = Query(None),
    total_capacity: int | None = Query(None, description="Restaurant total seat capacity"),
):
    try:
        dt = datetime.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")

    predictions = predict_peak(dt, tenant_id=tenant_id, total_capacity=total_capacity)
    return {
        "date": date,
        "predictions": [
            {
                "hour": p.hour,
                "predicted_occupancy": p.predicted_occupancy,
                "confidence": p.confidence,
                "label": p.label,
            }
            for p in predictions
        ],
    }


@router.post("/peak")
async def get_peak_prediction_with_history(data: dict):
    """Post historical data for more accurate predictions."""
    date_str = data.get("date")
    if not date_str:
        raise HTTPException(status_code=400, detail="date field required")

    try:
        dt = datetime.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    predictions = predict_peak(
        dt,
        tenant_id=data.get("tenant_id"),
        historical_data=data.get("historical_data"),
        total_capacity=data.get("total_capacity"),
    )
    return {
        "date": date_str,
        "predictions": [
            {
                "hour": p.hour,
                "predicted_occupancy": p.predicted_occupancy,
                "confidence": p.confidence,
                "label": p.label,
            }
            for p in predictions
        ],
    }

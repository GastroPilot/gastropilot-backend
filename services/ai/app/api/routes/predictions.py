from __future__ import annotations
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from app.engines.peak_predictor import predict_peak

router = APIRouter(prefix="/ai/predictions", tags=["ai-predictions"])


@router.get("/peak")
async def get_peak_prediction(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    tenant_id: str | None = Query(None),
):
    try:
        dt = datetime.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")

    predictions = predict_peak(dt, tenant_id=tenant_id)
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

"""Smart Seating v2 ML endpoints — training, feedback, preferences, RevPASH."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.engines.revpash import calculate_revpash
from app.engines.seating_ml import get_engine
from app.schemas.seating_ml import (
    FeedbackResponse,
    GuestPreference,
    RevPASHReport,
    RevPASHReportRequest,
    SeatingFeedback,
    TablePreference,
    TrainRequest,
    TrainResponse,
)

router = APIRouter(prefix="/ai/seating/ml", tags=["ai-seating-ml"])


@router.post("/train", response_model=TrainResponse)
async def train_model(data: TrainRequest):
    """Trigger ML model training with historical seating data."""
    engine = get_engine(data.tenant_id)

    history_dicts = [entry.model_dump() for entry in data.history]
    result = engine.train(history_dicts)

    return TrainResponse(
        tenant_id=data.tenant_id,
        records_used=result["records_used"],
        model_accuracy=result["model_accuracy"],
        message=result["message"],
    )


@router.post("/feedback", response_model=FeedbackResponse)
async def record_feedback(data: SeatingFeedback):
    """Record seating outcome feedback for continuous learning."""
    engine = get_engine(data.tenant_id)

    feedback_dict = data.model_dump()
    feedback_dict["seated_at"] = data.seated_at.isoformat()
    count = engine.record_feedback(feedback_dict)

    return FeedbackResponse(
        accepted=True,
        feedback_count=count,
        message=f"Feedback recorded. {count} total entries buffered for next training.",
    )


@router.get("/preferences/{guest_id}", response_model=GuestPreference)
async def get_preferences(guest_id: str, tenant_id: str):
    """Get learned seating preferences for a guest."""
    engine = get_engine(tenant_id)
    pref = engine.get_guest_preference(guest_id)

    if pref is None:
        raise HTTPException(
            status_code=404,
            detail=f"No preference data found for guest {guest_id}",
        )

    return GuestPreference(
        guest_id=pref["guest_id"],
        preferred_tables=[TablePreference(**t) for t in pref["preferred_tables"]],
        preferred_areas=pref["preferred_areas"],
        avg_party_size=pref["avg_party_size"],
        avg_satisfaction=pref["avg_satisfaction"],
        total_visits=pref["total_visits"],
        data_source=pref["data_source"],
    )


@router.post("/revpash/report", response_model=RevPASHReport)
async def revpash_report(data: RevPASHReportRequest):
    """Generate RevPASH analytics report for tables."""
    tables_dicts = [t.model_dump() for t in data.tables]
    history_dicts = [h.model_dump() for h in data.history]

    table_results = calculate_revpash(tables_dicts, history_dicts)

    if not table_results:
        raise HTTPException(status_code=400, detail="No table data to analyze")

    avg_revpash = (
        sum(r["revpash"] for r in table_results) / len(table_results) if table_results else 0.0
    )

    best = table_results[0]["table_id"] if table_results else None
    worst = table_results[-1]["table_id"] if table_results else None

    return RevPASHReport(
        tenant_id=data.tenant_id,
        period_start=data.period_start,
        period_end=data.period_end,
        tables=table_results,
        avg_revpash=round(avg_revpash, 2),
        best_table_id=best,
        worst_table_id=worst,
    )

"""Pydantic v2 schemas for Smart Seating v2 ML endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

# ── Training ──────────────────────────────────────────────────────────────────


class SeatingHistoryEntry(BaseModel):
    """A single historical seating record used for model training."""

    guest_id: str
    table_id: str
    party_size: int = Field(ge=1)
    seated_at: datetime
    duration_minutes: float = Field(ge=0)
    satisfaction: float | None = Field(default=None, ge=0.0, le=5.0)
    revenue: float | None = Field(default=None, ge=0.0)
    area: str | None = None
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    hour: int | None = Field(default=None, ge=0, le=23)

    @model_validator(mode="after")
    def fill_time_fields(self) -> SeatingHistoryEntry:
        if self.day_of_week is None:
            self.day_of_week = self.seated_at.weekday()
        if self.hour is None:
            self.hour = self.seated_at.hour
        return self


class TrainRequest(BaseModel):
    """Payload to trigger ML model training."""

    tenant_id: str
    history: list[SeatingHistoryEntry] = Field(min_length=1)


class TrainResponse(BaseModel):
    tenant_id: str
    records_used: int
    model_accuracy: float | None = None
    message: str


# ── Feedback ──────────────────────────────────────────────────────────────────


class SeatingFeedback(BaseModel):
    """Post-seating outcome feedback for continuous learning."""

    tenant_id: str
    guest_id: str
    table_id: str
    party_size: int = Field(ge=1)
    seated_at: datetime
    actual_duration_minutes: float = Field(ge=0)
    satisfaction: float = Field(ge=0.0, le=5.0)
    revenue: float = Field(ge=0.0)
    area: str | None = None


class FeedbackResponse(BaseModel):
    accepted: bool
    feedback_count: int
    message: str


# ── Guest Preferences ────────────────────────────────────────────────────────


class TablePreference(BaseModel):
    table_id: str
    score: float
    visit_count: int


class GuestPreference(BaseModel):
    guest_id: str
    preferred_tables: list[TablePreference]
    preferred_areas: list[str]
    avg_party_size: float
    avg_satisfaction: float | None = None
    total_visits: int
    data_source: str = "ml"  # "ml" | "rule_based"


# ── RevPASH ──────────────────────────────────────────────────────────────────


class RevPASHTableInput(BaseModel):
    table_id: str
    capacity: int
    hours_available: float = Field(ge=0, description="Total hours table was available")


class TableRevPASH(BaseModel):
    table_id: str
    capacity: int
    total_revenue: float
    total_hours_available: float
    total_hours_occupied: float
    revpash: float
    occupancy_rate: float
    avg_turnover_minutes: float
    score: float = Field(description="Normalized 0-100 RevPASH efficiency score")


class RevPASHReport(BaseModel):
    tenant_id: str
    period_start: datetime
    period_end: datetime
    tables: list[TableRevPASH]
    avg_revpash: float
    best_table_id: str | None = None
    worst_table_id: str | None = None


class RevPASHReportRequest(BaseModel):
    tenant_id: str
    period_start: datetime
    period_end: datetime
    tables: list[RevPASHTableInput]
    history: list[SeatingHistoryEntry]

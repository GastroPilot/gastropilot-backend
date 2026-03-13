"""Review schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator


class ReviewCreateRequest(BaseModel):
    rating: int
    title: str | None = None
    text: str | None = None

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, v: int) -> int:
        if v < 1 or v > 5:
            raise ValueError("Rating must be between 1 and 5")
        return v


class ReviewResponse(BaseModel):
    id: UUID
    rating: int
    title: str | None = None
    text: str | None = None
    author_name: str
    is_verified: bool = False
    staff_reply: str | None = None
    staff_reply_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReviewReplyRequest(BaseModel):
    text: str


class ReviewListResponse(BaseModel):
    items: list[ReviewResponse]
    total: int
    average_rating: float | None = None

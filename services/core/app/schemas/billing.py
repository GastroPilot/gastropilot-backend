"""Stripe billing schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SubscriptionPlanResponse(BaseModel):
    id: str
    name: str
    price: float
    features: list[str] = []
    tier: str


class CreateCheckoutRequest(BaseModel):
    plan_id: str
    success_url: str
    cancel_url: str


class CheckoutResponse(BaseModel):
    checkout_url: str


class SubscriptionResponse(BaseModel):
    id: str
    plan: str
    status: str
    current_period_end: datetime | None = None


class BillingPortalResponse(BaseModel):
    url: str

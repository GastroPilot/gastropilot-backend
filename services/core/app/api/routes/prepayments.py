from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_staff_or_above
from app.models.prepayment import ReservationPrepayment
from app.models.reservation import Reservation
from app.models.user import User

router = APIRouter(prefix="/prepayments", tags=["prepayments"])


class PrepaymentCreate(BaseModel):
    reservation_id: UUID
    amount: float
    currency: str = "EUR"
    payment_provider: str = "sumup"
    return_url: str | None = None


class PrepaymentResponse(BaseModel):
    id: UUID
    reservation_id: UUID
    tenant_id: UUID
    amount: float
    currency: str
    payment_provider: str
    payment_id: str | None = None
    transaction_id: str | None = None
    status: str
    payment_data: dict | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    model_config = {"from_attributes": True}


@router.post("/", response_model=PrepaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_prepayment(
    request: Request,
    body: PrepaymentCreate,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint to initiate a prepayment for a reservation."""
    effective_tenant_id = getattr(request.state, "tenant_id", None)

    # Validate reservation exists
    res_result = await db.execute(select(Reservation).where(Reservation.id == body.reservation_id))
    reservation = res_result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if not effective_tenant_id:
        effective_tenant_id = reservation.tenant_id

    prepayment = ReservationPrepayment(
        reservation_id=body.reservation_id,
        tenant_id=effective_tenant_id,
        amount=body.amount,
        currency=body.currency,
        payment_provider=body.payment_provider,
        status="pending",
    )
    db.add(prepayment)
    await db.commit()
    await db.refresh(prepayment)
    return prepayment


@router.get("/", response_model=PrepaymentResponse)
async def get_prepayment(
    reservation_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint to get prepayment status for a reservation."""
    result = await db.execute(
        select(ReservationPrepayment)
        .where(ReservationPrepayment.reservation_id == reservation_id)
        .order_by(ReservationPrepayment.created_at.desc())
    )
    prepayment = result.scalars().first()
    if not prepayment:
        raise HTTPException(status_code=404, detail="No prepayment found for this reservation")
    return prepayment


@router.get("/by-tenant", response_model=list[PrepaymentResponse])
async def list_prepayments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_above),
):
    result = await db.execute(
        select(ReservationPrepayment).order_by(ReservationPrepayment.created_at.desc())
    )
    return result.scalars().all()

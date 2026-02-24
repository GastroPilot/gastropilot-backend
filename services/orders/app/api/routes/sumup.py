"""SumUp terminal management and payment endpoints."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_manager_or_above, require_staff_or_above
from app.core.config import settings
from app.models.order import Order, OrderItem, SumUpPayment

router = APIRouter(prefix="/sumup", tags=["sumup"])


class ReaderCreateRequest(BaseModel):
    pairing_code: str
    name: str
    metadata: dict | None = None

class PaymentRequest(BaseModel):
    reader_id: str | None = None
    amount: float
    currency: str = "EUR"
    description: str | None = None
    tip_rates: list[float] | None = None
    tip_timeout: int | None = None


async def _get_sumup_service():
    """Lazy-load SumUp service with configured API key."""
    # Import here to avoid circular dependency
    import sys
    from pathlib import Path
    # Use shared sumup_service from core or inline
    from httpx import AsyncClient, Timeout

    api_key = getattr(settings, "SUMUP_API_KEY", None)
    if not api_key:
        raise HTTPException(status_code=503, detail="SumUp not configured")
    return api_key


# --- Reader endpoints ---

@router.get("/readers")
async def list_readers(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    from httpx import AsyncClient, Timeout
    api_key = await _get_sumup_service()
    merchant_code = getattr(settings, "SUMUP_MERCHANT_CODE", None)
    if not merchant_code:
        raise HTTPException(status_code=503, detail="SumUp merchant code not configured")

    async with AsyncClient(
        base_url="https://api.sumup.com",
        timeout=Timeout(30.0),
        headers={"Authorization": f"Bearer {api_key}"},
    ) as client:
        response = await client.get(f"/v0.1/merchants/{merchant_code}/readers")
        response.raise_for_status()
        return response.json()


@router.post("/readers")
async def create_reader(
    body: ReaderCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    from httpx import AsyncClient, Timeout
    api_key = await _get_sumup_service()
    merchant_code = getattr(settings, "SUMUP_MERCHANT_CODE", None)

    async with AsyncClient(
        base_url="https://api.sumup.com",
        timeout=Timeout(30.0),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    ) as client:
        response = await client.post(
            f"/v0.1/merchants/{merchant_code}/readers",
            json={"pairing_code": body.pairing_code, "name": body.name, "metadata": body.metadata},
        )
        response.raise_for_status()
        return response.json()


@router.get("/readers/{reader_id}")
async def get_reader(
    reader_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    from httpx import AsyncClient, Timeout
    api_key = await _get_sumup_service()
    merchant_code = getattr(settings, "SUMUP_MERCHANT_CODE", None)

    async with AsyncClient(
        base_url="https://api.sumup.com",
        timeout=Timeout(30.0),
        headers={"Authorization": f"Bearer {api_key}"},
    ) as client:
        response = await client.get(f"/v0.1/merchants/{merchant_code}/readers/{reader_id}")
        response.raise_for_status()
        return response.json()


@router.get("/readers/{reader_id}/status")
async def get_reader_status(
    reader_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    from httpx import AsyncClient, Timeout
    api_key = await _get_sumup_service()
    merchant_code = getattr(settings, "SUMUP_MERCHANT_CODE", None)

    async with AsyncClient(
        base_url="https://api.sumup.com",
        timeout=Timeout(30.0),
        headers={"Authorization": f"Bearer {api_key}"},
    ) as client:
        response = await client.get(
            f"/v0.1/merchants/{merchant_code}/readers/{reader_id}/status"
        )
        response.raise_for_status()
        return response.json()


# --- Payment endpoints ---

@router.post("/orders/{order_id}/pay")
async def initiate_payment(
    order_id: UUID,
    body: PaymentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    from httpx import AsyncClient, Timeout

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    api_key = await _get_sumup_service()
    merchant_code = getattr(settings, "SUMUP_MERCHANT_CODE", None)
    webhook_url = getattr(settings, "SUMUP_WEBHOOK_URL", None)

    checkout_ref = f"order_{order.id}_{uuid.uuid4()}"
    tenant_id = getattr(request.state, "tenant_id", order.tenant_id)

    # Create SumUp checkout
    async with AsyncClient(
        base_url="https://api.sumup.com",
        timeout=Timeout(30.0),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    ) as client:
        payload: dict = {
            "amount": body.amount,
            "currency": body.currency,
            "merchant_code": merchant_code,
            "checkout_reference": checkout_ref,
        }
        if body.description:
            payload["description"] = body.description
        if webhook_url:
            payload["return_url"] = webhook_url

        if body.reader_id:
            # Reader-specific checkout
            reader_payload: dict = {
                "total_amount": {
                    "currency": body.currency,
                    "minor_unit": 2,
                    "value": int(body.amount * 100),
                },
            }
            if body.description:
                reader_payload["description"] = body.description
            if webhook_url:
                reader_payload["return_url"] = webhook_url
            if body.tip_rates:
                reader_payload["tip_rates"] = body.tip_rates
            if body.tip_timeout:
                reader_payload["tip_timeout"] = max(30, min(120, body.tip_timeout))

            response = await client.post(
                f"/v0.1/merchants/{merchant_code}/readers/{body.reader_id}/checkout",
                json=reader_payload,
            )
        else:
            response = await client.post("/v0.1/checkouts", json=payload)

        response.raise_for_status()
        checkout_data = response.json()

    # Create payment record
    payment = SumUpPayment(
        order_id=order.id,
        tenant_id=tenant_id,
        checkout_id=checkout_data.get("id"),
        client_transaction_id=checkout_data.get("client_transaction_id", checkout_ref),
        reader_id=body.reader_id,
        amount=body.amount,
        currency=body.currency,
        status="processing",
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    return {
        "payment_id": str(payment.id),
        "checkout_id": checkout_data.get("id"),
        "client_transaction_id": payment.client_transaction_id,
        "reader_id": body.reader_id,
        "amount": body.amount,
        "currency": body.currency,
        "status": "processing",
        "message": "Payment initiated",
    }


@router.post("/readers/{reader_id}/terminate")
async def terminate_payment(
    reader_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    from httpx import AsyncClient, Timeout
    api_key = await _get_sumup_service()
    merchant_code = getattr(settings, "SUMUP_MERCHANT_CODE", None)

    async with AsyncClient(
        base_url="https://api.sumup.com",
        timeout=Timeout(30.0),
        headers={"Authorization": f"Bearer {api_key}"},
    ) as client:
        response = await client.post(
            f"/v0.1/merchants/{merchant_code}/readers/{reader_id}/terminate"
        )
        response.raise_for_status()

    return {"message": "Payment terminated"}


# --- Payment history ---

@router.get("/payments")
async def list_payments(
    status_filter: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    query = select(SumUpPayment).order_by(SumUpPayment.created_at.desc())
    if status_filter:
        query = query.where(SumUpPayment.status == status_filter)
    result = await db.execute(query)
    payments = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "order_id": str(p.order_id),
            "checkout_id": p.checkout_id,
            "amount": p.amount,
            "currency": p.currency,
            "status": p.status,
            "reader_id": p.reader_id,
            "initiated_at": p.initiated_at.isoformat() if p.initiated_at else None,
            "completed_at": p.completed_at.isoformat() if p.completed_at else None,
        }
        for p in payments
    ]


@router.get("/orders/{order_id}/payments")
async def list_order_payments(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    result = await db.execute(
        select(SumUpPayment)
        .where(SumUpPayment.order_id == order_id)
        .order_by(SumUpPayment.created_at.desc())
    )
    payments = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "checkout_id": p.checkout_id,
            "amount": p.amount,
            "status": p.status,
            "reader_id": p.reader_id,
            "initiated_at": p.initiated_at.isoformat() if p.initiated_at else None,
        }
        for p in payments
    ]

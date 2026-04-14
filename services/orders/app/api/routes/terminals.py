"""Provider-agnostic payment terminal management and payment endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_manager_or_above, require_staff_or_above
from app.models.order import Order
from app.models.terminal import PaymentTerminal, TerminalPayment
from app.services.terminal_provider import get_terminal_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/terminals", tags=["terminals"])


def _tenant_id(request: Request) -> uuid.UUID:
    tid = getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=400, detail="Kein Tenant-Kontext")
    return tid


# ---------------------------------------------------------------------------
# Terminal management
# ---------------------------------------------------------------------------


class TerminalCreateRequest(BaseModel):
    provider: str  # "sumup" | "manual"
    name: str
    # SumUp-specific
    pairing_code: str | None = None
    # General
    metadata: dict | None = None
    is_default: bool = False


class TerminalUpdateRequest(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    metadata: dict | None = None


@router.get("")
async def list_terminals(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    """List all terminals for this tenant, enriched with live status."""
    tenant_id = _tenant_id(request)

    result = await db.execute(
        select(PaymentTerminal)
        .where(PaymentTerminal.tenant_id == tenant_id)
        .order_by(PaymentTerminal.is_default.desc(), PaymentTerminal.name)
    )
    terminals = list(result.scalars().all())

    items = []
    for t in terminals:
        item = {
            "id": str(t.id),
            "provider": t.provider,
            "name": t.name,
            "provider_terminal_id": t.provider_terminal_id,
            "is_active": t.is_active,
            "is_default": t.is_default,
            "metadata": t.metadata_,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "live_status": None,
        }

        # Enrich with live status for API-connected providers
        if t.is_active and t.provider_terminal_id:
            try:
                provider = get_terminal_provider(t.provider)
                status = await provider.get_terminal_status(t)
                item["live_status"] = status
            except Exception:
                pass

        items.append(item)

    return items


@router.post("")
async def create_terminal(
    body: TerminalCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    """Register a new payment terminal."""
    tenant_id = _tenant_id(request)

    if body.provider not in ("sumup", "manual"):
        raise HTTPException(status_code=400, detail=f"Unbekannter Provider: {body.provider}")

    provider = get_terminal_provider(body.provider)
    provider_terminal_id = None

    # Provider-specific pairing
    if body.provider == "sumup":
        if not body.pairing_code:
            raise HTTPException(status_code=400, detail="Pairing-Code erforderlich für SumUp")
        pair_result = await provider.pair_terminal(
            tenant_id, pairing_code=body.pairing_code, name=body.name, metadata=body.metadata
        )
        provider_terminal_id = pair_result.get("provider_terminal_id")

    # Clear existing default if this is the new default
    if body.is_default:
        existing = await db.execute(
            select(PaymentTerminal).where(
                PaymentTerminal.tenant_id == tenant_id,
                PaymentTerminal.is_default.is_(True),
            )
        )
        for t in existing.scalars().all():
            t.is_default = False

    terminal = PaymentTerminal(
        tenant_id=tenant_id,
        provider=body.provider,
        name=body.name,
        provider_terminal_id=provider_terminal_id,
        is_default=body.is_default,
        metadata_=body.metadata,
    )
    db.add(terminal)
    await db.commit()
    await db.refresh(terminal)

    return {
        "id": str(terminal.id),
        "provider": terminal.provider,
        "name": terminal.name,
        "provider_terminal_id": terminal.provider_terminal_id,
        "is_active": terminal.is_active,
        "is_default": terminal.is_default,
        "metadata": terminal.metadata_,
        "created_at": terminal.created_at.isoformat() if terminal.created_at else None,
    }


@router.put("/{terminal_id}")
async def update_terminal(
    terminal_id: uuid.UUID,
    body: TerminalUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    """Update a terminal (rename, set default, deactivate)."""
    tenant_id = _tenant_id(request)
    result = await db.execute(
        select(PaymentTerminal).where(
            PaymentTerminal.id == terminal_id,
            PaymentTerminal.tenant_id == tenant_id,
        )
    )
    terminal = result.scalar_one_or_none()
    if not terminal:
        raise HTTPException(status_code=404, detail="Terminal nicht gefunden")

    if body.name is not None:
        terminal.name = body.name
    if body.is_active is not None:
        terminal.is_active = body.is_active
    if body.metadata is not None:
        terminal.metadata_ = body.metadata

    if body.is_default is True:
        # Clear other defaults
        others = await db.execute(
            select(PaymentTerminal).where(
                PaymentTerminal.tenant_id == tenant_id,
                PaymentTerminal.is_default.is_(True),
                PaymentTerminal.id != terminal_id,
            )
        )
        for t in others.scalars().all():
            t.is_default = False
        terminal.is_default = True
    elif body.is_default is False:
        terminal.is_default = False

    await db.commit()
    return {"status": "updated", "id": str(terminal.id)}


@router.delete("/{terminal_id}")
async def delete_terminal(
    terminal_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager_or_above),
):
    """Remove a terminal."""
    tenant_id = _tenant_id(request)
    result = await db.execute(
        select(PaymentTerminal).where(
            PaymentTerminal.id == terminal_id,
            PaymentTerminal.tenant_id == tenant_id,
        )
    )
    terminal = result.scalar_one_or_none()
    if not terminal:
        raise HTTPException(status_code=404, detail="Terminal nicht gefunden")

    await db.delete(terminal)
    await db.commit()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


class PaymentInitRequest(BaseModel):
    terminal_id: str  # UUID of PaymentTerminal
    amount: float
    currency: str = "EUR"
    description: str | None = None
    tip_rates: list[float] | None = None
    tip_timeout: int | None = None


@router.post("/orders/{order_id}/pay")
async def initiate_payment(
    order_id: uuid.UUID,
    body: PaymentInitRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    """Initiate a payment on any terminal provider."""
    tenant_id = _tenant_id(request)

    # Load order
    order_result = await db.execute(select(Order).where(Order.id == order_id))
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Bestellung nicht gefunden")

    # Load terminal
    term_result = await db.execute(
        select(PaymentTerminal).where(
            PaymentTerminal.id == uuid.UUID(body.terminal_id),
            PaymentTerminal.tenant_id == tenant_id,
            PaymentTerminal.is_active.is_(True),
        )
    )
    terminal = term_result.scalar_one_or_none()
    if not terminal:
        raise HTTPException(status_code=404, detail="Terminal nicht gefunden oder inaktiv")

    # Delegate to provider
    provider = get_terminal_provider(terminal.provider)
    result = await provider.initiate_payment(
        terminal, order, body.amount, body.currency,
        description=body.description,
        tip_rates=body.tip_rates,
        tip_timeout=body.tip_timeout,
    )

    # Create payment record
    payment = TerminalPayment(
        order_id=order_id,
        tenant_id=tenant_id,
        terminal_id=terminal.id,
        provider=terminal.provider,
        amount=body.amount,
        currency=body.currency,
        status=result["status"],
        provider_data=result.get("provider_data"),
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    # For manual terminals in awaiting_confirmation: also write to SumUpPayment
    # for backward compatibility is NOT needed — they are separate flows

    return {
        "payment_id": str(payment.id),
        "terminal_id": str(terminal.id),
        "provider": terminal.provider,
        "status": payment.status,
        "amount": payment.amount,
        "currency": payment.currency,
        "provider_data": payment.provider_data,
    }


@router.post("/payments/{payment_id}/confirm")
async def confirm_payment(
    payment_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    """Confirm a manual terminal payment."""
    tenant_id = _tenant_id(request)

    result = await db.execute(
        select(TerminalPayment).where(
            TerminalPayment.id == payment_id,
            TerminalPayment.tenant_id == tenant_id,
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Zahlung nicht gefunden")
    if payment.status not in ("awaiting_confirmation", "processing", "pending"):
        raise HTTPException(status_code=409, detail=f"Zahlung kann nicht bestätigt werden (Status: {payment.status})")

    provider = get_terminal_provider(payment.provider)
    new_status = await provider.confirm_payment(payment)

    payment.status = new_status
    payment.completed_at = datetime.now(UTC)

    # Update order
    order_result = await db.execute(select(Order).where(Order.id == payment.order_id))
    order = order_result.scalar_one_or_none()
    if order and new_status == "successful":
        order.payment_status = "paid"
        order.payment_method = f"{payment.provider}_card"
        order.paid_at = datetime.now(UTC)

        # Trigger TSE signing
        try:
            from app.services.fiskaly_service import sign_order_receipt

            await sign_order_receipt(db, order, payment_type="NON_CASH")
        except Exception as exc:
            logger.warning("TSE signing after terminal confirm failed: %s", exc)

    await db.commit()

    return {
        "payment_id": str(payment.id),
        "status": payment.status,
        "completed_at": payment.completed_at.isoformat() if payment.completed_at else None,
    }


@router.post("/payments/{payment_id}/cancel")
async def cancel_payment(
    payment_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    """Cancel a terminal payment."""
    tenant_id = _tenant_id(request)

    result = await db.execute(
        select(TerminalPayment).where(
            TerminalPayment.id == payment_id,
            TerminalPayment.tenant_id == tenant_id,
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Zahlung nicht gefunden")
    if payment.status in ("successful", "canceled"):
        raise HTTPException(status_code=409, detail=f"Zahlung kann nicht abgebrochen werden (Status: {payment.status})")

    provider = get_terminal_provider(payment.provider)
    new_status = await provider.cancel_payment(payment)

    payment.status = new_status
    payment.completed_at = datetime.now(UTC)
    await db.commit()

    return {"payment_id": str(payment.id), "status": payment.status}


@router.get("/orders/{order_id}/payments")
async def list_order_payments(
    order_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    """List terminal payments for an order."""
    tenant_id = _tenant_id(request)

    result = await db.execute(
        select(TerminalPayment)
        .where(
            TerminalPayment.order_id == order_id,
            TerminalPayment.tenant_id == tenant_id,
        )
        .order_by(TerminalPayment.initiated_at.desc())
    )
    payments = result.scalars().all()

    return [
        {
            "id": str(p.id),
            "order_id": str(p.order_id),
            "terminal_id": str(p.terminal_id) if p.terminal_id else None,
            "provider": p.provider,
            "amount": p.amount,
            "currency": p.currency,
            "status": p.status,
            "provider_data": p.provider_data,
            "error": p.error,
            "initiated_at": p.initiated_at.isoformat() if p.initiated_at else None,
            "completed_at": p.completed_at.isoformat() if p.completed_at else None,
        }
        for p in payments
    ]


@router.get("/payments")
async def list_payments(
    request: Request,
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    """List recent terminal payments."""
    tenant_id = _tenant_id(request)

    query = (
        select(TerminalPayment)
        .where(TerminalPayment.tenant_id == tenant_id)
        .order_by(TerminalPayment.initiated_at.desc())
        .limit(limit)
    )
    if status:
        query = query.where(TerminalPayment.status == status)

    result = await db.execute(query)
    payments = result.scalars().all()

    return [
        {
            "id": str(p.id),
            "order_id": str(p.order_id),
            "terminal_id": str(p.terminal_id) if p.terminal_id else None,
            "provider": p.provider,
            "amount": p.amount,
            "currency": p.currency,
            "status": p.status,
            "initiated_at": p.initiated_at.isoformat() if p.initiated_at else None,
            "completed_at": p.completed_at.isoformat() if p.completed_at else None,
        }
        for p in payments
    ]

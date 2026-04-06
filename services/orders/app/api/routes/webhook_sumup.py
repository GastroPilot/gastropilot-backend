"""SumUp webhook receiver for payment status updates."""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factories
from app.models.order import Order, SumUpPayment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/sumup")
async def sumup_webhook(request: Request):
    """Handle SumUp payment webhooks. No auth — uses signature verification."""
    body = await request.json()
    raw_body = await request.body()

    # Signature verification (optional — depends on config)
    from app.core.config import settings

    webhook_secret = getattr(settings, "SUMUP_WEBHOOK_SECRET", None)
    if webhook_secret:
        signature = request.headers.get("x-payload-signature", "")
        expected = hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=401, detail="Invalid signature")

    event_type = body.get("event_type") or body.get("type", "")
    event_type = event_type.lower().replace("_", ".")

    # Normalize event types
    if "checkout" in event_type and "status" in event_type:
        status_value = body.get("status", "").upper()
        if status_value == "PAID":
            event_type = "payment.succeeded"
        elif status_value == "FAILED":
            event_type = "payment.failed"

    _, session_factory_admin = get_session_factories()
    async with session_factory_admin() as db:
        # Find payment record
        payment = None

        # Strategy 1: client_transaction_id
        client_tx_id = body.get("client_transaction_id")
        if client_tx_id:
            result = await db.execute(
                select(SumUpPayment).where(SumUpPayment.client_transaction_id == client_tx_id)
            )
            payment = result.scalar_one_or_none()

        # Strategy 2: checkout_id
        if not payment:
            checkout_id = body.get("id") or body.get("checkout_id")
            if checkout_id:
                result = await db.execute(
                    select(SumUpPayment).where(SumUpPayment.checkout_id == str(checkout_id))
                )
                payment = result.scalar_one_or_none()

        # Strategy 3: checkout_reference
        if not payment:
            ref = body.get("checkout_reference", "")
            if ref.startswith("order_"):
                parts = ref.split("_")
                if len(parts) >= 2:
                    try:
                        from uuid import UUID

                        order_uuid = UUID(parts[1])
                        result = await db.execute(
                            select(SumUpPayment)
                            .where(SumUpPayment.order_id == order_uuid)
                            .order_by(SumUpPayment.created_at.desc())
                        )
                        payment = result.scalars().first()
                    except (ValueError, IndexError):
                        pass

        # Strategy 4: recent payment by status
        if not payment:
            cutoff = datetime.now(UTC) - timedelta(minutes=5)
            result = await db.execute(
                select(SumUpPayment)
                .where(
                    and_(
                        SumUpPayment.status == "processing",
                        SumUpPayment.created_at >= cutoff,
                    )
                )
                .order_by(SumUpPayment.created_at.desc())
            )
            payment = result.scalars().first()

        if not payment:
            logger.warning(f"No matching payment found for webhook: {body}")
            return {"status": "ignored", "reason": "No matching payment found"}

        # Update payment record
        payment.webhook_data = body

        if event_type == "payment.succeeded":
            payment.status = "successful"
            payment.completed_at = datetime.now(UTC)
            payment.transaction_code = body.get("transaction_code")
            payment.transaction_id = body.get("transaction_id") or body.get("id")

            # Update order
            result = await db.execute(select(Order).where(Order.id == payment.order_id))
            order = result.scalar_one_or_none()
            if order:
                order.payment_status = "paid"
                order.payment_method = "sumup_card"
                order.paid_at = datetime.now(UTC)

                # TSE signing (non-blocking)
                try:
                    from app.services.fiskaly_service import sign_order_receipt

                    await sign_order_receipt(db, order, payment_type="NON_CASH")
                except Exception as exc:
                    logger.error("fiskaly TSE signing failed for order %s: %s", order.id, exc)

        elif event_type in ("payment.failed", "payment.canceled"):
            payment.status = "failed" if "failed" in event_type else "canceled"

        await db.commit()

        return {
            "status": "processed",
            "event_type": event_type,
            "order_id": str(payment.order_id),
            "payment_id": str(payment.id),
        }

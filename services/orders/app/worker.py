from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from celery import Celery

from app.core.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "orders",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Berlin",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)


def _run_async(coro) -> None:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="orders.generate_receipt", bind=True, max_retries=3)
def generate_receipt(
    self,
    *,
    order_id: str,
    tenant_id: str,
) -> dict:
    """
    Generiert einen Bon (Receipt) für eine abgeschlossene Bestellung.
    Holt Order-Daten aus der DB und erstellt ein PDF/JSON-Dokument.
    """
    logger.info("Bon-Generierung für Order %s (Tenant %s)", order_id, tenant_id)

    async def _generate():
        from sqlalchemy import select

        from app.core.database import get_session_factories
        from app.models.order import Order, OrderItem

        factories = get_session_factories()
        async with factories["app"]() as session:
            # Tenant-Kontext setzen
            await session.execute(f"SELECT set_tenant_context('{tenant_id}', 'staff')")
            result = await session.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()
            if not order:
                logger.error("Order %s nicht gefunden", order_id)
                return {"error": "order_not_found"}

            items_result = await session.execute(
                select(OrderItem).where(OrderItem.order_id == order.id)
            )
            items = items_result.scalars().all()

            receipt = {
                "order_id": str(order.id),
                "order_number": order.order_number,
                "status": order.status,
                "total": sum(i.price * i.quantity for i in items),
                "items": [
                    {
                        "name": i.name,
                        "quantity": i.quantity,
                        "price": i.price,
                        "subtotal": i.price * i.quantity,
                    }
                    for i in items
                ],
            }
            return receipt

    try:
        return _run_async(_generate())
    except Exception as exc:
        logger.error("Bon-Generierung fehlgeschlagen für %s: %s", order_id, exc)
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="orders.order_completed_report", bind=True, max_retries=2)
def order_completed_report(
    self,
    *,
    order_id: str,
    tenant_id: str,
) -> dict:
    """
    Erstellt einen Abschluss-Report für eine fertige Bestellung.
    Kann für Tages-Statistiken genutzt werden.
    """
    logger.info("Abschluss-Report für Order %s", order_id)

    async def _report():
        from sqlalchemy import select

        from app.core.database import get_session_factories
        from app.models.order import Order

        factories = get_session_factories()
        async with factories["app"]() as session:
            await session.execute(f"SELECT set_tenant_context('{tenant_id}', 'staff')")
            result = await session.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()
            if not order:
                return {"error": "order_not_found"}

            return {
                "order_id": str(order.id),
                "tenant_id": tenant_id,
                "status": order.status,
                "table_id": str(order.table_id) if order.table_id else None,
            }

    try:
        return _run_async(_report())
    except Exception as exc:
        logger.error("Report-Generierung fehlgeschlagen für %s: %s", order_id, exc)
        raise self.retry(exc=exc, countdown=120)

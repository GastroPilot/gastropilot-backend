from __future__ import annotations

import json
import logging
from uuid import UUID

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def publish_event(
    event_name: str,
    payload: dict,
    tenant_id: UUID | str,
) -> None:
    """Publiziert ein Event via Redis Pub/Sub."""
    r = get_redis()
    message = json.dumps(payload, default=str)
    channel = f"gastropilot:{tenant_id}:{event_name}"
    global_channel = f"gastropilot:global:{event_name}"

    try:
        await r.publish(channel, message)
        await r.publish(global_channel, message)
        logger.debug("Event publiziert: %s auf %s", event_name, channel)
    except Exception as exc:
        logger.error("Fehler beim Publizieren von Event %s: %s", event_name, exc)


# Vordefinierte Event-Helfer


async def order_created(order_id: UUID, tenant_id: UUID, order_data: dict) -> None:
    await publish_event(
        "order.created",
        {"order_id": str(order_id), "tenant_id": str(tenant_id), **order_data},
        tenant_id,
    )


async def order_status_changed(
    order_id: UUID,
    tenant_id: UUID,
    old_status: str,
    new_status: str,
) -> None:
    await publish_event(
        f"order.{new_status}",
        {
            "order_id": str(order_id),
            "tenant_id": str(tenant_id),
            "old_status": old_status,
            "new_status": new_status,
        },
        tenant_id,
    )


async def order_ready(order_id: UUID, tenant_id: UUID, table_id: str | None = None) -> None:
    await publish_event(
        "order.ready",
        {"order_id": str(order_id), "tenant_id": str(tenant_id), "table_id": table_id},
        tenant_id,
    )

from __future__ import annotations
import json
import logging
from uuid import UUID

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: aioredis.Redis | None = None

# TTL für gecachte Order-Zustände (1 Stunde)
ORDER_CACHE_TTL = 3600


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def cache_order_status(
    order_id: UUID,
    tenant_id: UUID,
    status: str,
    extra: dict | None = None,
) -> None:
    r = get_redis()
    key = f"order:status:{tenant_id}:{order_id}"
    data = {"status": status, "order_id": str(order_id)}
    if extra:
        data.update(extra)
    try:
        await r.setex(key, ORDER_CACHE_TTL, json.dumps(data))
    except Exception as exc:
        logger.warning("Order-Status-Cache Fehler: %s", exc)


async def get_cached_order_status(order_id: UUID, tenant_id: UUID) -> dict | None:
    r = get_redis()
    key = f"order:status:{tenant_id}:{order_id}"
    try:
        raw = await r.get(key)
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logger.warning("Cache-Lesefehler: %s", exc)
    return None


async def invalidate_order_cache(order_id: UUID, tenant_id: UUID) -> None:
    r = get_redis()
    key = f"order:status:{tenant_id}:{order_id}"
    try:
        await r.delete(key)
    except Exception as exc:
        logger.warning("Cache-Löschfehler: %s", exc)


async def get_kitchen_queue_ids(tenant_id: UUID) -> list[str]:
    """Gibt gecachte Kitchen-Queue-IDs für einen Tenant zurück."""
    r = get_redis()
    key = f"kitchen:queue:{tenant_id}"
    try:
        raw = await r.get(key)
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logger.warning("Kitchen-Queue-Cache Fehler: %s", exc)
    return []


async def update_kitchen_queue(tenant_id: UUID, order_ids: list[str]) -> None:
    r = get_redis()
    key = f"kitchen:queue:{tenant_id}"
    try:
        await r.setex(key, 300, json.dumps(order_ids))  # 5 Minuten TTL
    except Exception as exc:
        logger.warning("Kitchen-Queue-Update Fehler: %s", exc)

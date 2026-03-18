from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Event constants
RESERVATION_CREATED = "reservation.created"
RESERVATION_CONFIRMED = "reservation.confirmed"
RESERVATION_CANCELED = "reservation.canceled"
RESERVATION_SEATED = "reservation.seated"
RESERVATION_COMPLETED = "reservation.completed"
RESERVATION_NO_SHOW = "reservation.no_show"
RESERVATION_REMINDER = "reservation.reminder"

ORDER_CREATED = "order.created"
ORDER_UPDATED = "order.updated"
ORDER_SENT_TO_KITCHEN = "order.sent_to_kitchen"
ORDER_READY = "order.ready"
ORDER_SERVED = "order.served"
ORDER_PAID = "order.paid"
ORDER_CANCELED = "order.canceled"

TABLE_UPDATED = "table.updated"
TABLE_STATUS_CHANGED = "table.status_changed"

USER_LOGGED_IN = "user.logged_in"
USER_LOGGED_OUT = "user.logged_out"

TENANT_SUSPENDED = "tenant.suspended"
TENANT_ACTIVATED = "tenant.activated"

BLOCK_CREATED = "block.created"
BLOCK_DELETED = "block.deleted"

WAITLIST_ADDED = "waitlist.added"
WAITLIST_NOTIFIED = "waitlist.notified"

PASSWORD_RESET_REQUESTED = "password_reset.requested"

MESSAGE_SENT = "message.sent"


class EventPublisher:
    """
    Publishes events via Redis Pub/Sub.
    Events are published to channels: gastropilot:{tenant_id}:{event_name}
    """

    def __init__(self, redis_client=None):
        self._redis = redis_client

    def set_redis(self, redis_client) -> None:
        self._redis = redis_client

    async def publish(
        self,
        event_name: str,
        payload: dict[str, Any],
        tenant_id: str | None = None,
    ) -> None:
        if not self._redis:
            logger.warning(f"Redis not configured, cannot publish event: {event_name}")
            return

        try:
            message = json.dumps(
                {
                    "event": event_name,
                    "tenant_id": tenant_id,
                    "data": payload,
                }
            )

            if tenant_id:
                channel = f"gastropilot:{tenant_id}:{event_name}"
                await self._redis.publish(channel, message)

            global_channel = f"gastropilot:global:{event_name}"
            await self._redis.publish(global_channel, message)

        except Exception as e:
            logger.error(f"Failed to publish event {event_name}: {e}", exc_info=True)


event_publisher = EventPublisher()

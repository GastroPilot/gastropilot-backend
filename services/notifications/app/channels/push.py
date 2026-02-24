from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


@dataclass
class PushMessage:
    to: str
    title: str
    body: str
    data: dict | None = None
    sound: str = "default"
    badge: int | None = None
    channel_id: str | None = None


async def send_push_notification(message: PushMessage) -> bool:
    if not settings.PUSH_ENABLED:
        logger.debug("Push-Benachrichtigungen deaktiviert – überspringe %s", message.to)
        return False

    if not message.to.startswith("ExponentPushToken["):
        logger.warning("Ungültiges Expo-Push-Token: %s", message.to)
        return False

    payload: dict = {
        "to": message.to,
        "title": message.title,
        "body": message.body,
        "sound": message.sound,
    }
    if message.data:
        payload["data"] = message.data
    if message.badge is not None:
        payload["badge"] = message.badge
    if message.channel_id:
        payload["channelId"] = message.channel_id

    headers: dict = {"Content-Type": "application/json"}
    if settings.EXPO_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {settings.EXPO_ACCESS_TOKEN}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(EXPO_PUSH_URL, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            if result.get("data", {}).get("status") == "error":
                logger.error("Expo Push Fehler: %s", result["data"].get("message"))
                return False
            logger.info("Push-Benachrichtigung gesendet an %s", message.to)
            return True
    except httpx.HTTPError as exc:
        logger.error("HTTP-Fehler beim Push-Versand: %s", exc)
        return False


async def send_bulk_push(messages: list[PushMessage]) -> dict[str, bool]:
    if not settings.PUSH_ENABLED:
        return {m.to: False for m in messages}

    payloads = []
    for m in messages:
        p: dict = {"to": m.to, "title": m.title, "body": m.body, "sound": m.sound}
        if m.data:
            p["data"] = m.data
        if m.badge is not None:
            p["badge"] = m.badge
        if m.channel_id:
            p["channelId"] = m.channel_id
        payloads.append(p)

    headers: dict = {"Content-Type": "application/json"}
    if settings.EXPO_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {settings.EXPO_ACCESS_TOKEN}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(EXPO_PUSH_URL, json=payloads, headers=headers)
            response.raise_for_status()
            results = response.json().get("data", [])
            return {m.to: (r.get("status") == "ok") for m, r in zip(messages, results)}
    except httpx.HTTPError as exc:
        logger.error("HTTP-Fehler beim Bulk-Push-Versand: %s", exc)
        return {m.to: False for m in messages}

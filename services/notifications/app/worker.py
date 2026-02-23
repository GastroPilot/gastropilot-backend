from __future__ import annotations
import asyncio
import json
import logging
from typing import Any

import redis
from celery import Celery

from app.core.config import settings
from app.channels.email import render_template, send_email
from app.channels.push import PushMessage, send_push_notification
from app.channels.sms import send_sms

logger = logging.getLogger(__name__)

celery_app = Celery(
    "notifications",
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


def _run_async(coro: Any) -> Any:
    """Führt eine Coroutine synchron im Celery-Kontext aus."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Reservierungs-Benachrichtigungen
# ---------------------------------------------------------------------------

@celery_app.task(name="notifications.send_reservation_confirmation", bind=True, max_retries=3)
def send_reservation_confirmation(
    self,
    *,
    guest_email: str,
    guest_name: str,
    restaurant_name: str,
    reservation_date: str,
    reservation_time: str,
    party_size: int,
    table_name: str | None = None,
    notes: str | None = None,
    guest_push_token: str | None = None,
    guest_phone: str | None = None,
) -> dict:
    results: dict = {}

    context = {
        "guest_name": guest_name,
        "restaurant_name": restaurant_name,
        "reservation_date": reservation_date,
        "reservation_time": reservation_time,
        "party_size": party_size,
        "table_name": table_name,
        "notes": notes,
    }

    # E-Mail
    try:
        html = render_template("reservation_confirmed.html", context)
        success = _run_async(
            send_email(
                to=guest_email,
                subject=f"Reservierung bestätigt – {restaurant_name}",
                html_body=html,
            )
        )
        results["email"] = success
    except Exception as exc:
        logger.error("E-Mail-Fehler bei Reservierungsbestätigung: %s", exc)
        results["email"] = False
        raise self.retry(exc=exc, countdown=60)

    # Push
    if guest_push_token:
        try:
            msg = PushMessage(
                to=guest_push_token,
                title=f"Reservierung bestätigt – {restaurant_name}",
                body=f"{reservation_date} um {reservation_time} Uhr · {party_size} Personen",
                data={"type": "reservation_confirmed"},
                channel_id="reservations",
            )
            results["push"] = _run_async(send_push_notification(msg))
        except Exception as exc:
            logger.error("Push-Fehler bei Reservierungsbestätigung: %s", exc)
            results["push"] = False

    # SMS
    if guest_phone:
        try:
            sms_text = (
                f"Ihre Reservierung bei {restaurant_name} am {reservation_date} "
                f"um {reservation_time} Uhr für {party_size} Personen ist bestätigt."
            )
            results["sms"] = _run_async(send_sms(guest_phone, sms_text))
        except Exception as exc:
            logger.error("SMS-Fehler bei Reservierungsbestätigung: %s", exc)
            results["sms"] = False

    return results


@celery_app.task(name="notifications.send_reservation_reminder", bind=True, max_retries=3)
def send_reservation_reminder(
    self,
    *,
    guest_email: str,
    guest_name: str,
    restaurant_name: str,
    reservation_time: str,
    party_size: int,
    table_name: str | None = None,
    guest_push_token: str | None = None,
    guest_phone: str | None = None,
) -> dict:
    results: dict = {}

    context = {
        "guest_name": guest_name,
        "restaurant_name": restaurant_name,
        "reservation_time": reservation_time,
        "party_size": party_size,
        "table_name": table_name,
    }

    try:
        html = render_template("reservation_reminder.html", context)
        success = _run_async(
            send_email(
                to=guest_email,
                subject=f"Erinnerung: Heute Abend bei {restaurant_name}",
                html_body=html,
            )
        )
        results["email"] = success
    except Exception as exc:
        logger.error("E-Mail-Fehler bei Reservierungserinnerung: %s", exc)
        results["email"] = False
        raise self.retry(exc=exc, countdown=60)

    if guest_push_token:
        try:
            msg = PushMessage(
                to=guest_push_token,
                title=f"Heute Abend: {restaurant_name}",
                body=f"Ihre Reservierung um {reservation_time} Uhr – wir freuen uns auf Sie!",
                data={"type": "reservation_reminder"},
                channel_id="reservations",
            )
            results["push"] = _run_async(send_push_notification(msg))
        except Exception as exc:
            logger.error("Push-Fehler bei Reservierungserinnerung: %s", exc)
            results["push"] = False

    if guest_phone:
        try:
            sms_text = (
                f"Erinnerung: Heute Abend um {reservation_time} Uhr bei {restaurant_name}. "
                f"Wir freuen uns auf Ihren Besuch!"
            )
            results["sms"] = _run_async(send_sms(guest_phone, sms_text))
        except Exception as exc:
            logger.error("SMS-Fehler bei Reservierungserinnerung: %s", exc)
            results["sms"] = False

    return results


# ---------------------------------------------------------------------------
# Bestell-Benachrichtigungen
# ---------------------------------------------------------------------------

@celery_app.task(name="notifications.send_order_ready", bind=True, max_retries=3)
def send_order_ready(
    self,
    *,
    guest_email: str | None = None,
    guest_name: str,
    restaurant_name: str,
    order_number: str,
    items: list[dict] | None = None,
    total: str | None = None,
    guest_push_token: str | None = None,
    guest_phone: str | None = None,
) -> dict:
    results: dict = {}

    if guest_email:
        context = {
            "guest_name": guest_name,
            "restaurant_name": restaurant_name,
            "order_number": order_number,
            "items": items or [],
            "total": total,
        }
        try:
            html = render_template("order_ready.html", context)
            success = _run_async(
                send_email(
                    to=guest_email,
                    subject=f"Bestellung #{order_number} ist fertig!",
                    html_body=html,
                )
            )
            results["email"] = success
        except Exception as exc:
            logger.error("E-Mail-Fehler bei Bestellbenachrichtigung: %s", exc)
            results["email"] = False
            raise self.retry(exc=exc, countdown=30)

    if guest_push_token:
        try:
            msg = PushMessage(
                to=guest_push_token,
                title="Ihre Bestellung ist fertig! 🍽️",
                body=f"Bestellung #{order_number} bei {restaurant_name} – bitte abholen.",
                data={"type": "order_ready", "order_number": order_number},
                channel_id="orders",
            )
            results["push"] = _run_async(send_push_notification(msg))
        except Exception as exc:
            logger.error("Push-Fehler bei Bestellbenachrichtigung: %s", exc)
            results["push"] = False

    if guest_phone:
        try:
            sms_text = f"Ihre Bestellung #{order_number} bei {restaurant_name} ist fertig zur Abholung."
            results["sms"] = _run_async(send_sms(guest_phone, sms_text))
        except Exception as exc:
            logger.error("SMS-Fehler bei Bestellbenachrichtigung: %s", exc)
            results["sms"] = False

    return results


# ---------------------------------------------------------------------------
# Redis Pub/Sub Consumer (läuft als separate Celery Beat-Task oder Worker)
# ---------------------------------------------------------------------------

@celery_app.task(name="notifications.process_redis_event")
def process_redis_event(event_name: str, payload_json: str) -> None:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        logger.error("Ungültiges JSON in Redis-Event: %s", payload_json)
        return

    logger.info("Redis-Event empfangen: %s", event_name)

    if event_name == "reservation.confirmed":
        send_reservation_confirmation.delay(**payload)
    elif event_name == "reservation.reminder":
        send_reservation_reminder.delay(**payload)
    elif event_name == "order.ready":
        send_order_ready.delay(**payload)
    else:
        logger.debug("Unbekanntes Event, wird ignoriert: %s", event_name)


def start_redis_consumer() -> None:
    """Startet einen blockierenden Redis Pub/Sub Consumer."""
    r = redis.from_url(settings.REDIS_URL)
    pubsub = r.pubsub()
    pubsub.psubscribe("gastropilot:*")

    logger.info("Redis Pub/Sub Consumer gestartet, abonniert: gastropilot:*")

    for message in pubsub.listen():
        if message["type"] not in ("message", "pmessage"):
            continue
        channel = message["channel"]
        if isinstance(channel, bytes):
            channel = channel.decode()

        # Channel-Format: gastropilot:{tenant_id}:{event_name}
        parts = channel.split(":", 2)
        event_name = parts[2] if len(parts) == 3 else channel

        data = message["data"]
        if isinstance(data, bytes):
            data = data.decode()

        process_redis_event.delay(event_name, data)

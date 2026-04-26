from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import redis
from celery import Celery

from app.channels.apns_liveactivity import (
    APNsConfigurationError,
    APNsTokenExpiredError,
    send_live_activity_end,
    send_live_activity_update,
)
from app.channels.email import render_template, send_email
from app.channels.push import PushMessage, send_push_notification
from app.channels.sms import send_sms
from app.core.config import settings

logger = logging.getLogger(__name__)


def _store_inbox_notification(
    *,
    guest_profile_id: str | None,
    tenant_id: str | None,
    notification_type: str,
    title: str,
    body: str | None = None,
    data: dict | None = None,
) -> None:
    """Write a notification row to the inbox (sync, best-effort)."""
    if not guest_profile_id or not settings.DATABASE_URL:
        return
    try:
        import psycopg2

        conn = psycopg2.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO notifications "
                    "(guest_profile_id, tenant_id, type, title, body, data) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        guest_profile_id,
                        tenant_id,
                        notification_type,
                        title,
                        body,
                        json.dumps(data or {}),
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Failed to store inbox notification: %s", exc)


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
    guest_profile_id: str | None = None,
    tenant_id: str | None = None,
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

    _store_inbox_notification(
        guest_profile_id=guest_profile_id,
        tenant_id=tenant_id,
        notification_type="reservation_confirmed",
        title=f"Reservierung bestätigt – {restaurant_name}",
        body=(f"{reservation_date} um {reservation_time} Uhr · {party_size} Personen"),
        data={"type": "reservation_confirmed"},
    )

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
# Passwort-Reset
# ---------------------------------------------------------------------------


@celery_app.task(name="notifications.send_password_reset", bind=True, max_retries=3)
def send_password_reset(
    self,
    *,
    guest_email: str,
    guest_name: str,
    reset_url: str,
) -> dict:
    results: dict = {}

    context = {
        "guest_name": guest_name,
        "reset_url": reset_url,
    }

    try:
        html = render_template("password_reset.html", context)
        success = _run_async(
            send_email(
                to=guest_email,
                subject="Passwort zurücksetzen – GastroPilot",
                html_body=html,
            )
        )
        results["email"] = success
    except Exception as exc:
        logger.error("E-Mail-Fehler bei Passwort-Reset: %s", exc)
        results["email"] = False
        raise self.retry(exc=exc, countdown=60)

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
    guest_profile_id: str | None = None,
    tenant_id: str | None = None,
) -> dict:
    results: dict = {}

    _store_inbox_notification(
        guest_profile_id=guest_profile_id,
        tenant_id=tenant_id,
        notification_type="order_ready",
        title=f"Bestellung #{order_number} ist fertig!",
        body=f"Ihre Bestellung bei {restaurant_name} ist bereit.",
        data={"type": "order_ready", "order_number": order_number},
    )

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
            sms_text = (
                f"Ihre Bestellung #{order_number} bei {restaurant_name} ist fertig zur Abholung."
            )
            results["sms"] = _run_async(send_sms(guest_phone, sms_text))
        except Exception as exc:
            logger.error("SMS-Fehler bei Bestellbenachrichtigung: %s", exc)
            results["sms"] = False

    return results


# ---------------------------------------------------------------------------
# Stornierung
# ---------------------------------------------------------------------------


@celery_app.task(name="notifications.send_reservation_canceled", bind=True, max_retries=3)
def send_reservation_canceled(
    self,
    *,
    guest_email: str,
    guest_name: str,
    restaurant_name: str,
    reservation_date: str,
    reservation_time: str,
    party_size: int,
    guest_push_token: str | None = None,
    guest_phone: str | None = None,
    guest_profile_id: str | None = None,
    tenant_id: str | None = None,
) -> dict:
    results: dict = {}

    _store_inbox_notification(
        guest_profile_id=guest_profile_id,
        tenant_id=tenant_id,
        notification_type="reservation_canceled",
        title=f"Reservierung storniert – {restaurant_name}",
        body=(
            f"Ihre Reservierung am {reservation_date} um {reservation_time} Uhr wurde storniert."
        ),
        data={"type": "reservation_canceled"},
    )

    context = {
        "guest_name": guest_name,
        "restaurant_name": restaurant_name,
        "reservation_date": reservation_date,
        "reservation_time": reservation_time,
        "party_size": party_size,
    }

    try:
        html = render_template("reservation_canceled.html", context)
        success = _run_async(
            send_email(
                to=guest_email,
                subject=f"Reservierung storniert – {restaurant_name}",
                html_body=html,
            )
        )
        results["email"] = success
    except Exception as exc:
        logger.error("E-Mail-Fehler bei Stornierung: %s", exc)
        results["email"] = False
        raise self.retry(exc=exc, countdown=60)

    if guest_phone:
        try:
            sms_text = (
                f"Ihre Reservierung bei {restaurant_name} am {reservation_date} "
                f"um {reservation_time} Uhr wurde storniert."
            )
            results["sms"] = _run_async(send_sms(guest_phone, sms_text))
        except Exception as exc:
            results["sms"] = False

    return results


# ---------------------------------------------------------------------------
# Warteliste
# ---------------------------------------------------------------------------


@celery_app.task(name="notifications.send_waitlist_notification", bind=True, max_retries=3)
def send_waitlist_notification(
    self,
    *,
    guest_email: str,
    guest_name: str,
    restaurant_name: str,
    reservation_date: str,
    party_size: int,
    guest_phone: str | None = None,
) -> dict:
    results: dict = {}

    context = {
        "guest_name": guest_name,
        "restaurant_name": restaurant_name,
        "reservation_date": reservation_date,
        "party_size": party_size,
    }

    try:
        html = render_template("waitlist_notification.html", context)
        success = _run_async(
            send_email(
                to=guest_email,
                subject=f"Platz frei – {restaurant_name}",
                html_body=html,
            )
        )
        results["email"] = success
    except Exception as exc:
        logger.error("E-Mail-Fehler bei Warteliste: %s", exc)
        results["email"] = False
        raise self.retry(exc=exc, countdown=60)

    if guest_phone:
        try:
            sms_text = (
                f"Gute Neuigkeiten! Bei {restaurant_name} ist ein Platz "
                f"am {reservation_date} frei geworden. Reservieren Sie jetzt!"
            )
            results["sms"] = _run_async(send_sms(guest_phone, sms_text))
        except Exception as exc:
            results["sms"] = False

    return results


# ---------------------------------------------------------------------------
# iOS Live Activity (APNs)
# ---------------------------------------------------------------------------


# Mapping interner Order-Status → guest-facing State, das die iOS-Activity zeigt.
_LIVE_ACTIVITY_STATUS_MAP = {
    "open": "ordered",
    "sent_to_kitchen": "preparing",
    "in_preparation": "preparing",
    "ready": "ready",
    "served": "served",
    "paid": "served",
    "canceled": "cancelled",
}

# Status, ab denen die Live Activity nach Delay beendet wird.
_LIVE_ACTIVITY_TERMINAL_STATUSES = {"served", "paid", "canceled"}


def _live_activity_db_dsn() -> str | None:
    """Wandelt den asyncpg-DSN in einen psycopg2-tauglichen DSN um."""
    if not settings.DATABASE_URL:
        return None
    return settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


def _fetch_active_live_activity_tokens(order_id: str) -> list[dict]:
    """Liest aktive Tokens (ended_at IS NULL) für die Order via psycopg2."""
    dsn = _live_activity_db_dsn()
    if not dsn:
        logger.debug("DATABASE_URL fehlt – keine Live Activity Tokens lesbar")
        return []

    try:
        import psycopg2

        conn = psycopg2.connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id::text, push_token, tenant_id::text "
                    "FROM live_activity_tokens "
                    "WHERE order_id = %s AND ended_at IS NULL",
                    (order_id,),
                )
                rows = cur.fetchall()
            return [{"id": r[0], "push_token": r[1], "tenant_id": r[2]} for r in rows]
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Konnte Live Activity Tokens nicht lesen: %s", exc)
        return []


def _mark_live_activity_token_ended(token_id: str) -> None:
    dsn = _live_activity_db_dsn()
    if not dsn:
        return
    try:
        import psycopg2

        conn = psycopg2.connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE live_activity_tokens "
                    "SET ended_at = NOW() WHERE id = %s AND ended_at IS NULL",
                    (token_id,),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Konnte Live Activity Token nicht beenden: %s", exc)


async def _dispatch_live_activity_update(
    token_id: str,
    push_token: str,
    content_state: dict,
    *,
    end: bool,
) -> None:
    """Sendet ein Update oder End-Event an APNs und behandelt 410."""
    try:
        if end:
            await send_live_activity_end(push_token, content_state)
        else:
            await send_live_activity_update(push_token, content_state)
    except APNsTokenExpiredError:
        logger.info("Live Activity Token abgelaufen – markiere ended_at: %s", token_id)
        _mark_live_activity_token_ended(token_id)
    except APNsConfigurationError as exc:
        logger.error("APNs nicht konfiguriert, überspringe Live Activity Update: %s", exc)
    except Exception:
        logger.exception("Unerwarteter Fehler beim Live Activity Versand")


@celery_app.task(name="notifications.send_live_activity_update")
def send_live_activity_update_task(
    *,
    order_id: str,
    new_status: str,
    tenant_id: str | None = None,
    eta_minutes: int | None = None,
    extra: dict | None = None,
) -> dict:
    """Sendet pro aktivem Token ein Live-Activity-Update."""
    tokens = _fetch_active_live_activity_tokens(order_id)
    if not tokens:
        return {"sent": 0, "tokens": 0}

    public_status = _LIVE_ACTIVITY_STATUS_MAP.get(new_status, new_status)
    content_state: dict = {
        "status": public_status,
        "internal_status": new_status,
        "order_id": order_id,
    }
    if tenant_id:
        content_state["tenant_id"] = tenant_id
    if eta_minutes is not None:
        content_state["eta_minutes"] = eta_minutes
    if extra:
        content_state.update(extra)

    for token in tokens:
        _run_async(
            _dispatch_live_activity_update(
                token_id=token["id"],
                push_token=token["push_token"],
                content_state=content_state,
                end=False,
            )
        )

    # Bei terminalem Status terminales End-Event nach Delay einplanen.
    if new_status in _LIVE_ACTIVITY_TERMINAL_STATUSES:
        delay = max(0, settings.LIVE_ACTIVITY_END_DELAY_SECONDS)
        end_live_activity_task.apply_async(
            kwargs={
                "order_id": order_id,
                "final_status": new_status,
                "tenant_id": tenant_id,
            },
            countdown=delay,
        )

    return {"sent": len(tokens), "tokens": len(tokens)}


@celery_app.task(name="notifications.end_live_activity")
def end_live_activity_task(
    *,
    order_id: str,
    final_status: str,
    tenant_id: str | None = None,
) -> dict:
    """Beendet alle aktiven Live Activities einer Order (event=end + ended_at)."""
    tokens = _fetch_active_live_activity_tokens(order_id)
    if not tokens:
        return {"ended": 0}

    public_status = _LIVE_ACTIVITY_STATUS_MAP.get(final_status, final_status)
    content_state = {
        "status": public_status,
        "internal_status": final_status,
        "order_id": order_id,
    }
    if tenant_id:
        content_state["tenant_id"] = tenant_id

    for token in tokens:
        _run_async(
            _dispatch_live_activity_update(
                token_id=token["id"],
                push_token=token["push_token"],
                content_state=content_state,
                end=True,
            )
        )
        _mark_live_activity_token_ended(token["id"])

    return {"ended": len(tokens)}


def _maybe_dispatch_live_activity_for_order_event(event_name: str, payload: dict) -> None:
    """Routet Order-Status-Events zu ``send_live_activity_update_task``.

    Eingehende Events:  ``order.<status>`` (z.B. ``order.ready``, ``order.paid``).
    Spezial-Event:      ``order_status_changed`` (mit ``new_status`` im Payload).
    """
    new_status: str | None = None
    order_id = payload.get("order_id")
    tenant_id = payload.get("tenant_id")

    if event_name == "order_status_changed":
        new_status = payload.get("new_status")
    elif event_name.startswith("order."):
        candidate = event_name.split(".", 1)[1]
        if candidate in _LIVE_ACTIVITY_STATUS_MAP:
            new_status = candidate

    if not new_status or not order_id:
        return

    send_live_activity_update_task.delay(
        order_id=str(order_id),
        new_status=new_status,
        tenant_id=str(tenant_id) if tenant_id else None,
        eta_minutes=payload.get("eta_minutes"),
        extra=payload.get("live_activity_extra"),
    )


# ---------------------------------------------------------------------------
# Redis Pub/Sub Consumer
# ---------------------------------------------------------------------------


@celery_app.task(name="notifications.process_redis_event")
def process_redis_event(event_name: str, payload_json: str) -> None:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        logger.error("Ungueltiges JSON in Redis-Event: %s", payload_json)
        return

    logger.info("Redis-Event empfangen: %s", event_name)

    handler_map = {
        "reservation.confirmed": send_reservation_confirmation,
        "reservation.reminder": send_reservation_reminder,
        "reservation.canceled": send_reservation_canceled,
        "order.ready": send_order_ready,
        "waitlist.notified": send_waitlist_notification,
        "password_reset.requested": send_password_reset,
    }

    handler = handler_map.get(event_name)
    if handler:
        handler.delay(**payload)
    else:
        logger.debug("Unbekanntes Event, wird ignoriert: %s", event_name)

    # Live-Activity-Dispatch parallel zu allen Order-Status-Events.
    _maybe_dispatch_live_activity_for_order_event(event_name, payload)


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

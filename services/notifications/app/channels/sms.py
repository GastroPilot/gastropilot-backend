from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_sms(to: str, body: str) -> bool:
    if not settings.SMS_ENABLED:
        logger.debug("SMS deaktiviert – überspringe Versand an %s", to)
        return False

    if not all(
        [settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN, settings.TWILIO_FROM_NUMBER]
    ):
        logger.error("Twilio-Konfiguration unvollständig")
        return False

    try:
        from twilio.rest import Client

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=body,
            from_=settings.TWILIO_FROM_NUMBER,
            to=to,
        )
        logger.info("SMS gesendet an %s (SID: %s)", to, message.sid)
        return True
    except Exception as exc:
        logger.error("Twilio-Fehler beim SMS-Versand an %s: %s", to, exc)
        return False

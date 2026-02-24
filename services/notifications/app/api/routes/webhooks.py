"""Twilio WhatsApp webhook receiver."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Request, Response

from app.channels.whatsapp import clear_session, get_or_create_session, process_message
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/whatsapp")
async def handle_whatsapp_webhook(
    request: Request,
    From: str = Form(""),
    Body: str = Form(""),
    To: str = Form(""),
    ProfileName: str = Form(""),
    NumMedia: str = Form("0"),
):
    """Handle incoming WhatsApp messages from Twilio."""
    if not settings.WHATSAPP_ENABLED:
        return Response(content="<Response></Response>", media_type="application/xml")

    phone = From.replace("whatsapp:", "")
    text = Body.strip()

    if not phone or not text:
        return Response(content="<Response></Response>", media_type="application/xml")

    logger.info("WhatsApp message from %s: %s", phone, text[:100])

    # Determine restaurant slug from the Twilio number or a default
    # In production, map Twilio numbers to restaurant slugs via DB
    restaurant_slug = "default"

    try:
        response_text = await process_message(phone, restaurant_slug, text)
    except Exception as exc:
        logger.error("WhatsApp bot error for %s: %s", phone, exc)
        response_text = "Entschuldigung, ein Fehler ist aufgetreten. Bitte versuchen Sie es erneut."

    # Send response via Twilio
    await _send_whatsapp_reply(phone, response_text)

    # Return empty TwiML (we send the reply via API, not TwiML)
    return Response(content="<Response></Response>", media_type="application/xml")


async def _send_whatsapp_reply(to: str, body: str) -> bool:
    """Send a WhatsApp message via Twilio REST API."""
    if not all([settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN, settings.TWILIO_WHATSAPP_NUMBER]):
        logger.warning("Twilio WhatsApp not configured, skipping reply to %s", to)
        return False

    try:
        from twilio.rest import Client

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=body,
            from_=f"whatsapp:{settings.TWILIO_WHATSAPP_NUMBER}",
            to=f"whatsapp:{to}",
        )
        logger.info("WhatsApp reply sent to %s (SID: %s)", to, message.sid)
        return True
    except Exception as exc:
        logger.error("Failed to send WhatsApp reply to %s: %s", to, exc)
        return False

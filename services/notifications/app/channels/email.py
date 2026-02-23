from __future__ import annotations
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import settings

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def render_template(template_name: str, context: dict) -> str:
    template = _jinja_env.get_template(template_name)
    return template.render(**context)


async def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> bool:
    if not settings.EMAIL_ENABLED:
        logger.debug("E-Mail deaktiviert – überspringe Versand an %s", to)
        return False

    if settings.EMAIL_PROVIDER == "resend":
        return await _send_via_resend(to, subject, html_body, text_body)
    return await _send_via_smtp(to, subject, html_body, text_body)


async def _send_via_resend(
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None,
) -> bool:
    if not settings.RESEND_API_KEY:
        logger.error("RESEND_API_KEY nicht gesetzt")
        return False

    payload: dict = {
        "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>",
        "to": [to],
        "subject": subject,
        "html": html_body,
    }
    if text_body:
        payload["text"] = text_body

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            )
            response.raise_for_status()
            logger.info("E-Mail via Resend gesendet an %s", to)
            return True
    except httpx.HTTPError as exc:
        logger.error("Resend HTTP-Fehler: %s", exc)
        return False


async def _send_via_smtp(
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None,
) -> bool:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>"
    msg["To"] = to

    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
            smtp.ehlo()
            if settings.SMTP_PORT == 587:
                smtp.starttls()
            if settings.SMTP_USERNAME:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.sendmail(settings.EMAIL_FROM, to, msg.as_string())
        logger.info("E-Mail via SMTP gesendet an %s", to)
        return True
    except smtplib.SMTPException as exc:
        logger.error("SMTP-Fehler: %s", exc)
        return False

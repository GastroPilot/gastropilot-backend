"""
Notification Service für Multi-Channel Benachrichtigungen.

Unterstützt:
- E-Mail (via SMTP)
- SMS (via Twilio)
- WhatsApp (via Twilio WhatsApp API)
"""

import asyncio
import logging
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from pydantic import BaseModel, EmailStr

logger = logging.getLogger(__name__)


class UpsellPackageInfo(BaseModel):
    """Informationen über ein Upsell-Paket."""

    name: str
    price: float
    description: str | None = None


class ReservationNotification(BaseModel):
    """Daten für Reservierungsbenachrichtigung."""

    guest_name: str
    guest_email: EmailStr
    guest_phone: str
    restaurant_name: str
    restaurant_slug: str | None = None
    restaurant_address: str | None = None
    restaurant_phone: str | None = None
    confirmation_code: str
    date: str
    time: str
    party_size: int
    table_number: str | None = None
    special_requests: str | None = None
    manage_url: str | None = None  # URL zum Verwalten der Reservierung
    upsell_packages: list[UpsellPackageInfo] | None = None  # Bestellte Upsell-Pakete
    ics_content: str | None = None  # ICS-Datei-Inhalt für Kalender-Anhang


class NotificationResult(BaseModel):
    """Ergebnis einer Benachrichtigung."""

    channel: str
    success: bool
    message: str | None = None
    error: str | None = None


class NotificationService:
    """
    Service für das Senden von Benachrichtigungen über mehrere Kanäle.
    """

    def __init__(self):
        self._twilio_client = None
        self._smtp_configured = False
        self._initialized = False

    def _initialize(self):
        """Lazy initialization der externen Clients."""
        if self._initialized:
            return

        from app.settings import (
            SMTP_FROM_EMAIL,
            SMTP_HOST,
            SMTP_PASSWORD,
            SMTP_PORT,
            SMTP_USER,
            TWILIO_ACCOUNT_SID,
            TWILIO_AUTH_TOKEN,
            TWILIO_PHONE_NUMBER,
            TWILIO_WHATSAPP_NUMBER,
        )

        # Twilio Client
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
            try:
                from twilio.rest import Client

                self._twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                self._twilio_phone = TWILIO_PHONE_NUMBER
                self._twilio_whatsapp = TWILIO_WHATSAPP_NUMBER
                logger.info("Twilio client initialized")
            except ImportError:
                logger.warning("Twilio package not installed. SMS/WhatsApp disabled.")
            except Exception as e:
                logger.error(f"Failed to initialize Twilio: {e}")
        else:
            logger.info("Twilio not configured. SMS/WhatsApp disabled.")

        # SMTP Configuration
        if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
            self._smtp_host = SMTP_HOST
            self._smtp_port = SMTP_PORT
            self._smtp_user = SMTP_USER
            self._smtp_password = SMTP_PASSWORD
            self._smtp_from = SMTP_FROM_EMAIL
            self._smtp_configured = True
            logger.info("SMTP configured for email notifications")

        self._initialized = True

    async def send_reservation_confirmation(
        self,
        notification: ReservationNotification,
        channels: list[str] = None,
    ) -> list[NotificationResult]:
        """
        Sendet Reservierungsbestätigung über alle konfigurierten Kanäle.

        Args:
            notification: Reservierungsdaten
            channels: Liste der Kanäle ("email", "sms", "whatsapp") oder None für alle

        Returns:
            Liste der Ergebnisse pro Kanal
        """
        self._initialize()

        if channels is None:
            channels = ["email", "sms", "whatsapp"]

        results = []

        # E-Mail
        if "email" in channels:
            result = await self._send_email_confirmation(notification)
            results.append(result)

        # SMS
        if "sms" in channels:
            result = await self._send_sms_confirmation(notification)
            results.append(result)

        # WhatsApp
        if "whatsapp" in channels:
            result = await self._send_whatsapp_confirmation(notification)
            results.append(result)

        return results

    async def send_reservation_cancellation(
        self,
        notification: ReservationNotification,
        channels: list[str] = None,
    ) -> list[NotificationResult]:
        """Sendet Stornierungsbestätigung."""
        self._initialize()

        if channels is None:
            channels = ["email", "sms", "whatsapp"]

        results = []

        if "email" in channels:
            result = await self._send_email_cancellation(notification)
            results.append(result)

        if "sms" in channels:
            result = await self._send_sms_cancellation(notification)
            results.append(result)

        if "whatsapp" in channels:
            result = await self._send_whatsapp_cancellation(notification)
            results.append(result)

        return results

    # =========================================================================
    # E-Mail Methods
    # =========================================================================

    async def _send_email_confirmation(
        self,
        notification: ReservationNotification,
    ) -> NotificationResult:
        """Sendet E-Mail Bestätigung."""
        if self._smtp_configured:
            return await self._send_email_via_smtp(notification, "confirmation")
        else:
            return NotificationResult(
                channel="email",
                success=False,
                error="Email not configured",
            )

    async def _send_email_cancellation(
        self,
        notification: ReservationNotification,
    ) -> NotificationResult:
        """Sendet E-Mail Stornierungsbestätigung."""
        if self._smtp_configured:
            return await self._send_email_via_smtp(notification, "cancellation")
        else:
            return NotificationResult(
                channel="email",
                success=False,
                error="Email not configured",
            )

    async def _send_email_via_smtp(
        self,
        notification: ReservationNotification,
        email_type: str,
    ) -> NotificationResult:
        """Sendet E-Mail via SMTP."""
        try:
            if email_type == "confirmation":
                subject = f"Reservierungsbestätigung - {notification.restaurant_name}"
                body = self._build_confirmation_email_body(notification)
            else:
                subject = f"Stornierungsbestätigung - {notification.restaurant_name}"
                body = self._build_cancellation_email_body(notification)

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self._smtp_from
            msg["To"] = notification.guest_email

            msg.attach(MIMEText(body, "html"))

            # Füge ICS-Datei als Anhang hinzu, falls vorhanden
            if notification.ics_content:
                ics_attachment = MIMEBase("text", "calendar")
                ics_attachment.set_payload(notification.ics_content.encode("utf-8"))
                ics_attachment.add_header(
                    "Content-Disposition",
                    f'attachment; filename="reservation-{notification.confirmation_code}.ics"',
                )
                ics_attachment.add_header(
                    "Content-Type", "text/calendar; charset=utf-8; method=REQUEST"
                )
                encoders.encode_base64(ics_attachment)
                msg.attach(ics_attachment)

            # Send in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._smtp_send,
                msg,
            )

            logger.info(f"Email sent to {notification.guest_email}")
            return NotificationResult(
                channel="email",
                success=True,
                message=f"Email sent to {notification.guest_email}",
            )

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return NotificationResult(
                channel="email",
                success=False,
                error=str(e),
            )

    def _smtp_send(self, msg):
        """Synchrone SMTP-Sendung."""
        with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
            server.starttls()
            server.login(self._smtp_user, self._smtp_password)
            server.send_message(msg)

    def _build_confirmation_email_body(self, n: ReservationNotification) -> str:
        """Baut HTML E-Mail Body für Bestätigung."""

        # Optionale Sections
        table_section = (
            f"""
                        <tr>
                            <td style="padding: 16px 20px; border-bottom: 1px solid #f0f0f0;">
                                <table cellpadding="0" cellspacing="0" border="0" width="100%">
                                    <tr>
                                        <td style="width: 40px; vertical-align: top;">
                                            <div style="width: 36px; height: 36px; background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); border-radius: 8px; text-align: center; line-height: 36px; font-size: 18px;">🪑</div>
                                        </td>
                                        <td style="padding-left: 12px; vertical-align: middle;">
                                            <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px;">Ihr Tisch</div>
                                            <div style="font-size: 16px; font-weight: 600; color: #1f2937; margin-top: 2px;">{n.table_number if str(n.table_number or '').lower().startswith('tisch') else f'Tisch {n.table_number}'}</div>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>"""
            if n.table_number
            else ""
        )

        special_requests_section = (
            f"""
                    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top: 24px;">
                        <tr>
                            <td style="background: #fef3c7; border-radius: 12px; padding: 16px 20px; border-left: 4px solid #f59e0b;">
                                <div style="font-size: 12px; color: #92400e; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600;">📝 Besondere Wünsche</div>
                                <div style="font-size: 14px; color: #78350f; margin-top: 8px; line-height: 1.5;">{n.special_requests}</div>
                            </td>
                        </tr>
                    </table>"""
            if n.special_requests
            else ""
        )

        # Upsell-Pakete Section
        upsell_packages_section = ""
        if n.upsell_packages and len(n.upsell_packages) > 0:
            packages_html = ""
            total_price = 0.0
            for pkg in n.upsell_packages:
                total_price += pkg.price
                description_html = (
                    f'<div style="font-size: 13px; color: #6b7280; margin-top: 4px;">{pkg.description or ""}</div>'
                    if pkg.description
                    else ""
                )
                packages_html += f"""
                    <tr>
                        <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb;">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                                <div style="flex: 1;">
                                    <div style="font-size: 15px; font-weight: 600; color: #1f2937;">{pkg.name}</div>
                                    {description_html}
                                </div>
                                <div style="font-size: 15px; font-weight: 600; color: #7c3aed; margin-left: 16px;">{pkg.price:.2f} €</div>
                            </div>
                        </td>
                    </tr>"""

            upsell_packages_section = f"""
                    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top: 24px;">
                        <tr>
                            <td style="background: #faf5ff; border-radius: 12px; padding: 20px; border-left: 4px solid #7c3aed;">
                                <div style="font-size: 12px; color: #6b21a8; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; margin-bottom: 12px;">📦 Ihre Zusatzpakete</div>
                                <table cellpadding="0" cellspacing="0" border="0" width="100%">
                                    {packages_html}
                                    <tr>
                                        <td style="padding-top: 12px; border-top: 2px solid #c084fc;">
                                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                                <div style="font-size: 15px; font-weight: 700; color: #1f2937;">Gesamt</div>
                                                <div style="font-size: 18px; font-weight: 700; color: #7c3aed;">{total_price:.2f} €</div>
                                            </div>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                    </table>"""

        phone_line = (
            f'<div style="margin-top: 4px;">📞 {n.restaurant_phone}</div>'
            if n.restaurant_phone
            else ""
        )

        return f"""
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>Reservierungsbestätigung - {n.restaurant_name}</title>
    <!--[if mso]>
    <noscript>
        <xml>
            <o:OfficeDocumentSettings>
                <o:PixelsPerInch>96</o:PixelsPerInch>
            </o:OfficeDocumentSettings>
        </xml>
    </noscript>
    <![endif]-->
</head>
<body style="margin: 0; padding: 0; background-color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
    <!-- Wrapper -->
    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #f3f4f6; padding: 40px 20px;">
        <tr>
            <td align="center">
                <!-- Container -->
                <table cellpadding="0" cellspacing="0" border="0" width="600" style="max-width: 600px; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05), 0 10px 20px rgba(0, 0, 0, 0.05);">
                    
                    <!-- Header mit Gradient -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 40px 30px; text-align: center;">
                            <!-- Success Icon -->
                            <div style="width: 72px; height: 72px; background: rgba(255,255,255,0.2); border-radius: 50%; margin: 0 auto 20px; line-height: 72px; font-size: 36px;">✓</div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 700; letter-spacing: -0.5px;">Reservierung bestätigt!</h1>
                            <p style="margin: 12px 0 0; color: rgba(255,255,255,0.9); font-size: 16px;">{n.restaurant_name}</p>
                        </td>
                    </tr>
                    
                    <!-- Bestätigungscode Banner -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%); padding: 24px 30px; text-align: center; border-bottom: 1px solid #e5e7eb;">
                            <div style="font-size: 12px; color: #0369a1; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">Ihr Bestätigungscode</div>
                            <div style="font-size: 32px; font-weight: 800; color: #0c4a6e; letter-spacing: 4px; margin-top: 8px; font-family: 'Courier New', monospace;">{n.confirmation_code}</div>
                        </td>
                    </tr>
                    
                    <!-- Begrüßung -->
                    <tr>
                        <td style="padding: 32px 30px 16px;">
                            <p style="margin: 0; font-size: 16px; color: #374151; line-height: 1.6;">
                                Hallo <strong>{n.guest_name}</strong>,
                            </p>
                            <p style="margin: 12px 0 0; font-size: 16px; color: #6b7280; line-height: 1.6;">
                                vielen Dank für Ihre Reservierung! Wir freuen uns, Sie bei uns begrüßen zu dürfen. Hier sind Ihre Reservierungsdetails:
                            </p>
                        </td>
                    </tr>
                    
                    <!-- Reservierungsdetails Card -->
                    <tr>
                        <td style="padding: 0 30px 24px;">
                            <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background: #fafafa; border-radius: 12px; border: 1px solid #e5e7eb;">
                                <!-- Datum -->
                                <tr>
                                    <td style="padding: 16px 20px; border-bottom: 1px solid #f0f0f0;">
                                        <table cellpadding="0" cellspacing="0" border="0" width="100%">
                                            <tr>
                                                <td style="width: 40px; vertical-align: top;">
                                                    <div style="width: 36px; height: 36px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 8px; text-align: center; line-height: 36px; font-size: 18px;">📅</div>
                                                </td>
                                                <td style="padding-left: 12px; vertical-align: middle;">
                                                    <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px;">Datum</div>
                                                    <div style="font-size: 16px; font-weight: 600; color: #1f2937; margin-top: 2px;">{n.date}</div>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                <!-- Uhrzeit -->
                                <tr>
                                    <td style="padding: 16px 20px; border-bottom: 1px solid #f0f0f0;">
                                        <table cellpadding="0" cellspacing="0" border="0" width="100%">
                                            <tr>
                                                <td style="width: 40px; vertical-align: top;">
                                                    <div style="width: 36px; height: 36px; background: linear-gradient(135deg, #06b6d4 0%, #0891b2 100%); border-radius: 8px; text-align: center; line-height: 36px; font-size: 18px;">⏰</div>
                                                </td>
                                                <td style="padding-left: 12px; vertical-align: middle;">
                                                    <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px;">Uhrzeit</div>
                                                    <div style="font-size: 16px; font-weight: 600; color: #1f2937; margin-top: 2px;">{n.time} Uhr</div>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                <!-- Personen -->
                                <tr>
                                    <td style="padding: 16px 20px; border-bottom: 1px solid #f0f0f0;">
                                        <table cellpadding="0" cellspacing="0" border="0" width="100%">
                                            <tr>
                                                <td style="width: 40px; vertical-align: top;">
                                                    <div style="width: 36px; height: 36px; background: linear-gradient(135deg, #10b981 0%, #059669 100%); border-radius: 8px; text-align: center; line-height: 36px; font-size: 18px;">👥</div>
                                                </td>
                                                <td style="padding-left: 12px; vertical-align: middle;">
                                                    <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px;">Personen</div>
                                                    <div style="font-size: 16px; font-weight: 600; color: #1f2937; margin-top: 2px;">{n.party_size} {('Person' if n.party_size == 1 else 'Personen')}</div>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                <!-- Tisch (optional) -->
                                {table_section}
                                <!-- Name -->
                                <tr>
                                    <td style="padding: 16px 20px;">
                                        <table cellpadding="0" cellspacing="0" border="0" width="100%">
                                            <tr>
                                                <td style="width: 40px; vertical-align: top;">
                                                    <div style="width: 36px; height: 36px; background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%); border-radius: 8px; text-align: center; line-height: 36px; font-size: 18px;">👤</div>
                                                </td>
                                                <td style="padding-left: 12px; vertical-align: middle;">
                                                    <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px;">Reserviert auf</div>
                                                    <div style="font-size: 16px; font-weight: 600; color: #1f2937; margin-top: 2px;">{n.guest_name}</div>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                            
                            <!-- Upsell-Pakete (optional) -->
                            {upsell_packages_section}
                            
                            <!-- Besondere Wünsche (optional) -->
                            {special_requests_section}
                        </td>
                    </tr>
                    
                    <!-- Restaurant Info -->
                    <tr>
                        <td style="padding: 0 30px 32px;">
                            <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background: linear-gradient(135deg, #1f2937 0%, #111827 100%); border-radius: 12px; overflow: hidden;">
                                <tr>
                                    <td style="padding: 24px;">
                                        <div style="font-size: 14px; color: #9ca3af; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; margin-bottom: 12px;">📍 So finden Sie uns</div>
                                        <div style="font-size: 18px; font-weight: 600; color: #ffffff; margin-bottom: 8px;">{n.restaurant_name}</div>
                                        <div style="font-size: 14px; color: #d1d5db; line-height: 1.6;">
                                            {n.restaurant_address or 'Adresse auf Anfrage'}
                                            {phone_line}
                                        </div>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Hinweise -->
                    <tr>
                        <td style="padding: 0 30px 32px;">
                            <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background: #f9fafb; border-radius: 12px; border: 1px solid #e5e7eb;">
                                <tr>
                                    <td style="padding: 20px;">
                                        <div style="font-size: 14px; font-weight: 600; color: #374151; margin-bottom: 12px;">💡 Gut zu wissen</div>
                                        <ul style="margin: 0; padding: 0 0 0 20px; font-size: 13px; color: #6b7280; line-height: 1.8;">
                                            <li>Bitte kommen Sie pünktlich zur reservierten Uhrzeit</li>
                                            <li>Bei Verspätung bitten wir um kurze telefonische Nachricht</li>
                                            <li>Stornierungen sind bis 2 Stunden vor der Reservierung möglich</li>
                                            <li>Ihren Bestätigungscode können Sie zur Änderung oder Stornierung nutzen</li>
                                        </ul>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Reservierung verwalten -->
                    <tr>
                        <td style="padding: 0 30px 32px;">
                            <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background: linear-gradient(135deg, #fafafa 0%, #f5f5f5 100%); border-radius: 12px; border: 1px solid #e5e7eb;">
                                <tr>
                                    <td style="padding: 24px; text-align: center;">
                                        <div style="font-size: 14px; font-weight: 600; color: #374151; margin-bottom: 16px;">✏️ Reservierung verwalten</div>
                                        
                                        <!-- Action Buttons -->
                                        <table cellpadding="0" cellspacing="0" border="0" width="100%">
                                            <tr>
                                                <td style="padding: 0 8px;" align="center">
                                                    <!--[if mso]>
                                                    <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{n.manage_url or '#'}" style="height:44px;v-text-anchor:middle;width:140px;" arcsize="18%" strokecolor="#667eea" strokeweight="1px" fillcolor="#ffffff">
                                                    <w:anchorlock/>
                                                    <center style="color:#667eea;font-family:sans-serif;font-size:14px;font-weight:600;">Bearbeiten</center>
                                                    </v:roundrect>
                                                    <![endif]-->
                                                    <!--[if !mso]><!-->
                                                    <a href="{n.manage_url or '#'}" style="display: inline-block; padding: 12px 24px; background: #ffffff; color: #667eea; text-decoration: none; font-weight: 600; font-size: 14px; border-radius: 8px; border: 2px solid #667eea; margin: 4px;">✏️ Bearbeiten</a>
                                                    <!--<![endif]-->
                                                </td>
                                                <td style="padding: 0 8px;" align="center">
                                                    <!--[if mso]>
                                                    <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{n.manage_url + '/cancel' if n.manage_url else '#'}" style="height:44px;v-text-anchor:middle;width:140px;" arcsize="18%" strokecolor="#ef4444" strokeweight="1px" fillcolor="#ffffff">
                                                    <w:anchorlock/>
                                                    <center style="color:#ef4444;font-family:sans-serif;font-size:14px;font-weight:600;">Stornieren</center>
                                                    </v:roundrect>
                                                    <![endif]-->
                                                    <!--[if !mso]><!-->
                                                    <a href="{n.manage_url + '/cancel' if n.manage_url else '#'}" style="display: inline-block; padding: 12px 24px; background: #ffffff; color: #ef4444; text-decoration: none; font-weight: 600; font-size: 14px; border-radius: 8px; border: 2px solid #ef4444; margin: 4px;">🗑️ Stornieren</a>
                                                    <!--<![endif]-->
                                                </td>
                                            </tr>
                                        </table>
                                        
                                        <p style="margin: 16px 0 0; font-size: 12px; color: #9ca3af;">
                                            Oder rufen Sie uns an: <a href="tel:{n.restaurant_phone or ''}" style="color: #667eea; text-decoration: none; font-weight: 500;">{n.restaurant_phone or 'Telefonnummer auf Anfrage'}</a>
                                        </p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- ICS Kalender-Hinweis -->
                    {'''
                    <tr>
                        <td style="padding: 0 30px 24px;">
                            <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background: #eff6ff; border-radius: 12px; border: 1px solid #bfdbfe;">
                                <tr>
                                    <td style="padding: 16px 20px; text-align: center;">
                                        <div style="font-size: 13px; color: #1e40af; line-height: 1.6;">
                                            📅 <strong>Kalender-Event</strong><br>
                                            Diese Reservierung wurde als Kalender-Event (.ics) an diese E-Mail angehängt. 
                                            Öffnen Sie die Datei, um die Reservierung zu Ihrem Kalender hinzuzufügen.
                                        </div>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    ''' if n.ics_content else ''}
                    
                    <!-- Footer -->
                    <tr>
                        <td style="background: #f9fafb; padding: 24px 30px; border-top: 1px solid #e5e7eb; text-align: center;">
                            <p style="margin: 0; font-size: 12px; color: #9ca3af;">
                                Diese E-Mail wurde automatisch versendet.<br>
                                Bitte antworten Sie nicht direkt auf diese E-Mail.
                            </p>
                            <p style="margin: 16px 0 0; font-size: 12px; color: #9ca3af;">
                                Powered by <strong style="color: #667eea;">GastroPilot</strong>
                            </p>
                        </td>
                    </tr>
                    
                </table>
                <!-- /Container -->
            </td>
        </tr>
    </table>
    <!-- /Wrapper -->
</body>
</html>
"""

    def _build_cancellation_email_body(self, n: ReservationNotification) -> str:
        """Baut HTML E-Mail Body für Stornierung."""

        phone_line = (
            f'<div style="margin-top: 4px;">📞 {n.restaurant_phone}</div>'
            if n.restaurant_phone
            else ""
        )

        return f"""
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>Stornierungsbestätigung - {n.restaurant_name}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
    <!-- Wrapper -->
    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #f3f4f6; padding: 40px 20px;">
        <tr>
            <td align="center">
                <!-- Container -->
                <table cellpadding="0" cellspacing="0" border="0" width="600" style="max-width: 600px; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05), 0 10px 20px rgba(0, 0, 0, 0.05);">
                    
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); padding: 40px 30px; text-align: center;">
                            <div style="width: 72px; height: 72px; background: rgba(255,255,255,0.2); border-radius: 50%; margin: 0 auto 20px; line-height: 72px; font-size: 36px;">✕</div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 700; letter-spacing: -0.5px;">Reservierung storniert</h1>
                            <p style="margin: 12px 0 0; color: rgba(255,255,255,0.9); font-size: 16px;">{n.restaurant_name}</p>
                        </td>
                    </tr>
                    
                    <!-- Content -->
                    <tr>
                        <td style="padding: 32px 30px;">
                            <p style="margin: 0; font-size: 16px; color: #374151; line-height: 1.6;">
                                Hallo <strong>{n.guest_name}</strong>,
                            </p>
                            <p style="margin: 16px 0 0; font-size: 16px; color: #6b7280; line-height: 1.6;">
                                Ihre Reservierung wurde erfolgreich storniert. Hier die Details der stornierten Reservierung:
                            </p>
                        </td>
                    </tr>
                    
                    <!-- Stornierte Details -->
                    <tr>
                        <td style="padding: 0 30px 24px;">
                            <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background: #fef2f2; border-radius: 12px; border: 1px solid #fecaca;">
                                <tr>
                                    <td style="padding: 20px;">
                                        <div style="text-decoration: line-through; color: #991b1b;">
                                            <div style="font-size: 14px; margin-bottom: 8px;">📅 {n.date}</div>
                                            <div style="font-size: 14px; margin-bottom: 8px;">⏰ {n.time} Uhr</div>
                                            <div style="font-size: 14px;">👥 {n.party_size} {('Person' if n.party_size == 1 else 'Personen')}</div>
                                        </div>
                                        <div style="margin-top: 16px; padding-top: 16px; border-top: 1px solid #fecaca;">
                                            <div style="font-size: 12px; color: #991b1b;">Bestätigungscode</div>
                                            <div style="font-size: 18px; font-weight: 700; color: #7f1d1d; font-family: monospace;">{n.confirmation_code}</div>
                                        </div>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Neue Reservierung -->
                    <tr>
                        <td style="padding: 0 30px 32px;">
                            <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border-radius: 12px; border: 1px solid #bbf7d0;">
                                <tr>
                                    <td style="padding: 24px; text-align: center;">
                                        <div style="font-size: 24px; margin-bottom: 12px;">🍽️</div>
                                        <div style="font-size: 16px; font-weight: 600; color: #166534; margin-bottom: 8px;">Wir freuen uns auf Ihren nächsten Besuch!</div>
                                        <div style="font-size: 14px; color: #15803d;">Möchten Sie einen neuen Termin buchen?</div>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Restaurant Info -->
                    <tr>
                        <td style="padding: 0 30px 32px;">
                            <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background: linear-gradient(135deg, #1f2937 0%, #111827 100%); border-radius: 12px; overflow: hidden;">
                                <tr>
                                    <td style="padding: 24px;">
                                        <div style="font-size: 14px; color: #9ca3af; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; margin-bottom: 12px;">📍 Kontakt</div>
                                        <div style="font-size: 18px; font-weight: 600; color: #ffffff; margin-bottom: 8px;">{n.restaurant_name}</div>
                                        <div style="font-size: 14px; color: #d1d5db; line-height: 1.6;">
                                            {n.restaurant_address or 'Adresse auf Anfrage'}
                                            {phone_line}
                                        </div>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="background: #f9fafb; padding: 24px 30px; border-top: 1px solid #e5e7eb; text-align: center;">
                            <p style="margin: 0; font-size: 12px; color: #9ca3af;">
                                Diese E-Mail wurde automatisch versendet.<br>
                                Bitte antworten Sie nicht direkt auf diese E-Mail.
                            </p>
                            <p style="margin: 16px 0 0; font-size: 12px; color: #9ca3af;">
                                Powered by <strong style="color: #667eea;">GastroPilot</strong>
                            </p>
                        </td>
                    </tr>
                    
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    # =========================================================================
    # SMS Methods
    # =========================================================================

    async def _send_sms_confirmation(
        self,
        notification: ReservationNotification,
    ) -> NotificationResult:
        """Sendet SMS Bestätigung via Twilio."""
        if not self._twilio_client:
            return NotificationResult(
                channel="sms",
                success=False,
                error="Twilio not configured",
            )

        try:
            message_body = (
                f"Reservierung bestätigt!\n"
                f"{notification.restaurant_name}\n"
                f"{notification.date} um {notification.time} Uhr\n"
                f"{notification.party_size} Personen\n"
                f"Code: {notification.confirmation_code}"
            )

            # Run in thread pool
            loop = asyncio.get_event_loop()
            message = await loop.run_in_executor(
                None,
                lambda: self._twilio_client.messages.create(
                    body=message_body,
                    from_=self._twilio_phone,
                    to=notification.guest_phone,
                ),
            )

            logger.info(f"SMS sent to {notification.guest_phone}: {message.sid}")
            return NotificationResult(
                channel="sms",
                success=True,
                message=f"SMS sent, SID: {message.sid}",
            )

        except Exception as e:
            logger.error(f"Failed to send SMS: {e}")
            return NotificationResult(
                channel="sms",
                success=False,
                error=str(e),
            )

    async def _send_sms_cancellation(
        self,
        notification: ReservationNotification,
    ) -> NotificationResult:
        """Sendet SMS Stornierungsbestätigung."""
        if not self._twilio_client:
            return NotificationResult(
                channel="sms",
                success=False,
                error="Twilio not configured",
            )

        try:
            message_body = (
                f"Reservierung storniert\n"
                f"{notification.restaurant_name}\n"
                f"{notification.date} um {notification.time} Uhr\n"
                f"Code: {notification.confirmation_code}"
            )

            loop = asyncio.get_event_loop()
            message = await loop.run_in_executor(
                None,
                lambda: self._twilio_client.messages.create(
                    body=message_body,
                    from_=self._twilio_phone,
                    to=notification.guest_phone,
                ),
            )

            logger.info(f"Cancellation SMS sent to {notification.guest_phone}")
            return NotificationResult(
                channel="sms",
                success=True,
                message=f"SMS sent, SID: {message.sid}",
            )

        except Exception as e:
            logger.error(f"Failed to send SMS: {e}")
            return NotificationResult(
                channel="sms",
                success=False,
                error=str(e),
            )

    # =========================================================================
    # WhatsApp Methods
    # =========================================================================

    async def _send_whatsapp_confirmation(
        self,
        notification: ReservationNotification,
    ) -> NotificationResult:
        """Sendet WhatsApp Bestätigung via Twilio."""
        if not self._twilio_client or not self._twilio_whatsapp:
            return NotificationResult(
                channel="whatsapp",
                success=False,
                error="WhatsApp not configured",
            )

        try:
            message_body = (
                f"✅ *Reservierung bestätigt!*\n\n"
                f"🍽️ {notification.restaurant_name}\n"
                f"📅 {notification.date}\n"
                f"🕐 {notification.time} Uhr\n"
                f"👥 {notification.party_size} Personen\n"
                f"🔑 Code: *{notification.confirmation_code}*\n\n"
                f"Wir freuen uns auf Ihren Besuch!"
            )

            # Format phone for WhatsApp
            phone = notification.guest_phone
            if not phone.startswith("whatsapp:"):
                phone = f"whatsapp:{phone}"

            loop = asyncio.get_event_loop()
            message = await loop.run_in_executor(
                None,
                lambda: self._twilio_client.messages.create(
                    body=message_body,
                    from_=self._twilio_whatsapp,
                    to=phone,
                ),
            )

            logger.info(f"WhatsApp sent to {notification.guest_phone}: {message.sid}")
            return NotificationResult(
                channel="whatsapp",
                success=True,
                message=f"WhatsApp sent, SID: {message.sid}",
            )

        except Exception as e:
            logger.error(f"Failed to send WhatsApp: {e}")
            return NotificationResult(
                channel="whatsapp",
                success=False,
                error=str(e),
            )

    async def _send_whatsapp_cancellation(
        self,
        notification: ReservationNotification,
    ) -> NotificationResult:
        """Sendet WhatsApp Stornierungsbestätigung."""
        if not self._twilio_client or not self._twilio_whatsapp:
            return NotificationResult(
                channel="whatsapp",
                success=False,
                error="WhatsApp not configured",
            )

        try:
            message_body = (
                f"❌ *Reservierung storniert*\n\n"
                f"Ihre Reservierung bei {notification.restaurant_name} "
                f"am {notification.date} um {notification.time} Uhr "
                f"wurde storniert.\n\n"
                f"Code: {notification.confirmation_code}\n\n"
                f"Wir hoffen, Sie bald wieder zu sehen!"
            )

            phone = notification.guest_phone
            if not phone.startswith("whatsapp:"):
                phone = f"whatsapp:{phone}"

            loop = asyncio.get_event_loop()
            message = await loop.run_in_executor(
                None,
                lambda: self._twilio_client.messages.create(
                    body=message_body,
                    from_=self._twilio_whatsapp,
                    to=phone,
                ),
            )

            logger.info(f"WhatsApp cancellation sent to {notification.guest_phone}")
            return NotificationResult(
                channel="whatsapp",
                success=True,
                message=f"WhatsApp sent, SID: {message.sid}",
            )

        except Exception as e:
            logger.error(f"Failed to send WhatsApp: {e}")
            return NotificationResult(
                channel="whatsapp",
                success=False,
                error=str(e),
            )

    async def send_whatsapp_message(
        self,
        to_phone: str,
        message: str,
    ) -> NotificationResult:
        """
        Sendet eine einzelne WhatsApp-Nachricht.

        Wird vom WhatsApp-Bot für Antworten verwendet.
        """
        if not self._twilio_client or not self._twilio_whatsapp:
            self._initialize()

        if not self._twilio_client or not self._twilio_whatsapp:
            return NotificationResult(
                channel="whatsapp",
                success=False,
                error="WhatsApp not configured",
            )

        try:
            phone = to_phone if to_phone.startswith("whatsapp:") else f"whatsapp:{to_phone}"

            loop = asyncio.get_event_loop()
            msg = await loop.run_in_executor(
                None,
                lambda: self._twilio_client.messages.create(
                    body=message,
                    from_=self._twilio_whatsapp,
                    to=phone,
                ),
            )

            return NotificationResult(
                channel="whatsapp",
                success=True,
                message=f"Message sent, SID: {msg.sid}",
            )

        except Exception as e:
            logger.error(f"Failed to send WhatsApp message: {e}")
            return NotificationResult(
                channel="whatsapp",
                success=False,
                error=str(e),
            )


# Singleton instance
notification_service = NotificationService()

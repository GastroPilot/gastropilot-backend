"""
SumUp Webhook Handler für Zahlungsbestätigungen.

Empfängt Webhooks von SumUp bei:
- Zahlungsabschluss
- Zahlungsfehler
- Zahlungsstornierung
"""

import hashlib
import hmac
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order, SumUpPayment
from app.dependencies import get_session
from app.services.sumup_service import SumUpService
from app.settings import SUMUP_API_KEY, SUMUP_MERCHANT_CODE, SUMUP_WEBHOOK_SECRET

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/sumup", tags=["webhooks"])


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verifiziert die Webhook-Signatur von SumUp.

    Args:
        payload: Request Body als Bytes
        signature: X-SumUp-Signature Header
        secret: Webhook Secret

    Returns:
        True wenn Signatur gültig ist
    """
    if not secret:
        logger.warning("SUMUP_WEBHOOK_SECRET nicht gesetzt - Webhook-Verifizierung übersprungen")
        return True  # In Development erlauben wir unverifizierte Webhooks

    try:
        # SumUp verwendet HMAC-SHA256
        expected_signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

        # Vergleich mit konstanter Zeit (timing-safe)
        return hmac.compare_digest(expected_signature, signature)
    except Exception as e:
        logger.error(f"Error verifying webhook signature: {e}")
        return False


@router.post("")
async def handle_sumup_webhook(
    request: Request,
    x_payload_signature: str | None = Header(None, alias="x-payload-signature"),
    session: AsyncSession = Depends(get_session),
):
    """
    Verarbeitet Webhooks von SumUp.

    Webhook-Events:
    - payment.succeeded: Zahlung erfolgreich
    - payment.failed: Zahlung fehlgeschlagen
    - payment.canceled: Zahlung abgebrochen

    Webhook-Payload Beispiel:
    {
        "event_type": "payment.succeeded",
        "event_id": "evt_...",
        "timestamp": "2023-01-20T15:16:17Z",
        "data": {
            "transaction_code": "TEENSK4W2K",
            "transaction_id": "410fc44a-5956-44e1-b5cc-19c6f8d727a4",
            "client_transaction_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "amount": 10.1,
            "currency": "EUR",
            "status": "SUCCESSFUL",
            ...
        }
    }
    """
    try:
        # Request Body lesen
        body = await request.body()

        # Webhook-Signatur verifizieren
        # SumUp verwendet den Header "x-payload-signature" für Webhook-Signaturen
        if x_payload_signature:
            if not verify_webhook_signature(body, x_payload_signature, SUMUP_WEBHOOK_SECRET):
                logger.warning(f"Invalid webhook signature: {x_payload_signature}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature"
                )

        # JSON parsen
        import json

        webhook_data = json.loads(body)

        event_type = webhook_data.get("event_type")
        event_id = webhook_data.get("event_id") or webhook_data.get("id")
        timestamp = webhook_data.get("timestamp")

        # SumUp verwendet unterschiedliche Strukturen für verschiedene Event-Types
        # payment.* Events verwenden "data", checkout.* Events verwenden "payload"
        # ABER: CHECKOUT_STATUS_CHANGED kann auch eine vereinfachte Struktur haben:
        # { "id": "...", "status": "...", "event_type": "CHECKOUT_STATUS_CHANGED" }
        event_type_normalized = event_type.lower() if event_type else ""

        # Bestimme, ob es ein payment.* oder checkout.* Event ist
        if "checkout" in event_type_normalized:
            # Checkout Events können "payload" haben ODER Daten direkt im Root
            data = webhook_data.get("payload", {})
            # Falls kein payload vorhanden, verwende Root-Daten
            if not data:
                data = webhook_data
        else:
            # Payment Events verwenden "data" (z.B. payment.succeeded)
            data = webhook_data.get("data", {})

        logger.info(f"SumUp webhook received: {event_type} (event_id: {event_id})")

        # Debug: Logge die vollständige Payload-Struktur für CHECKOUT Events
        if "checkout" in event_type_normalized:
            logger.warning("=== CHECKOUT Event Debug ===")
            logger.warning(f"Event Type: {event_type}")
            logger.warning(f"Webhook root keys: {list(webhook_data.keys())}")
            logger.warning(f"Payload object: {webhook_data.get('payload')}")
            logger.warning(f"Data object keys: {list(data.keys()) if data else 'None'}")
            logger.warning(
                f"Data object content: {json.dumps(data, indent=2, default=str) if data else 'None'}"
            )
            logger.warning(
                f"Full webhook structure: {json.dumps(webhook_data, indent=2, default=str)}"
            )
            logger.warning("===========================")

        # Transaction-Daten extrahieren (verschiedene Event-Types haben unterschiedliche Strukturen)
        # Für CHECKOUT_STATUS_CHANGED Events gibt es zwei mögliche Strukturen:
        # 1. Vollständig: { "payload": { "checkout_id": "...", "reference": "...", "status": "..." } }
        # 2. Vereinfacht: { "id": "...", "status": "...", "event_type": "CHECKOUT_STATUS_CHANGED" }
        #    Das "id" Feld IST die checkout_id (die durch create_checkout zurückgegeben wurde)

        client_transaction_id = data.get("client_transaction_id")
        # Für CHECKOUT_STATUS_CHANGED Events: Das "id" Feld im Root IST die checkout_id
        # (die durch create_checkout zurückgegeben wurde)
        checkout_id = (
            data.get("checkout_id")  # Für checkout.* Events direkt im payload/data
            or data.get("id")  # Für vereinfachte Struktur: "id" ist die checkout_id
            or webhook_data.get("checkout_id")  # Direkt im Root
        )

        # Für vereinfachte CHECKOUT_STATUS_CHANGED Events:
        # Das Root "id" IST die checkout_id (nicht die event_id)
        if not checkout_id and "checkout" in event_type_normalized:
            root_id = webhook_data.get("id")
            if root_id:
                checkout_id = root_id
                logger.info(f"Verwende Root 'id' als checkout_id: {checkout_id}")
        checkout_reference = (
            data.get("reference")  # Für checkout.* Events: "reference" (nicht "checkout_reference")
            or data.get("checkout_reference")  # Fallback
            or webhook_data.get("reference")  # Direkt im Root
        )
        transaction_code = data.get("transaction_code")
        transaction_id = data.get("transaction_id")
        amount = data.get("amount")
        currency = data.get("currency", "EUR")
        # Status kann direkt im Root sein für vereinfachte CHECKOUT_STATUS_CHANGED Events
        transaction_status = data.get("status") or webhook_data.get("status")

        # SumUpPayment-Eintrag finden - versuche verschiedene Identifikatoren
        sumup_payment = None

        # 1. Versuche client_transaction_id
        if client_transaction_id:
            result = await session.execute(
                select(SumUpPayment).where(
                    SumUpPayment.client_transaction_id == client_transaction_id
                )
            )
            sumup_payment = result.scalar_one_or_none()

        # 2. Versuche checkout_id (das "id" Feld im Webhook ist die checkout_id)
        if not sumup_payment and checkout_id:
            logger.info(f"Suche Payment über checkout_id: {checkout_id}")
            result = await session.execute(
                select(SumUpPayment).where(SumUpPayment.checkout_id == checkout_id)
            )
            sumup_payment = result.scalar_one_or_none()
            if sumup_payment:
                logger.info(
                    f"Payment gefunden über checkout_id: Payment ID {sumup_payment.id}, Order ID {sumup_payment.order_id}"
                )

        # 3. Versuche checkout_reference (falls vorhanden)
        if not sumup_payment and checkout_reference:
            # checkout_reference hat Format "order_{order_id}_{uuid}"
            # Versuche Order-ID zu extrahieren
            logger.info(f"Versuche Payment über checkout_reference zu finden: {checkout_reference}")
            if checkout_reference.startswith("order_"):
                try:
                    order_id_str = checkout_reference.split("_")[1]
                    order_id = int(order_id_str)
                    logger.info(f"Extrahiere Order-ID aus checkout_reference: {order_id}")
                    result = await session.execute(
                        select(SumUpPayment)
                        .where(SumUpPayment.order_id == order_id)
                        .order_by(SumUpPayment.created_at_utc.desc())
                    )
                    sumup_payment = result.scalar_one_or_none()
                    if sumup_payment:
                        logger.info(
                            f"Payment gefunden über checkout_reference: Payment ID {sumup_payment.id}, Order ID {order_id}"
                        )
                except (ValueError, IndexError) as e:
                    logger.warning(
                        f"Fehler beim Extrahieren der Order-ID aus checkout_reference '{checkout_reference}': {e}"
                    )
                    pass

        # 4. Fallback: Versuche alle Payments für die letzten 5 Minuten zu durchsuchen (nur für CHECKOUT Events)
        # Da der vereinfachte CHECKOUT_STATUS_CHANGED Webhook keine checkout_id enthält,
        # müssen wir über Zeitraum suchen. Der Webhook kommt kurz nach Checkout-Erstellung.
        if not sumup_payment and "checkout" in event_type_normalized:
            logger.warning("Fallback: Suche Payment in allen Payments der letzten 5 Minuten")
            # Suche in allen Payments der letzten 5 Minuten
            from datetime import timedelta

            cutoff_time = datetime.now(UTC) - timedelta(minutes=5)
            result = await session.execute(
                select(SumUpPayment)
                .where(SumUpPayment.created_at_utc >= cutoff_time)
                .order_by(SumUpPayment.created_at_utc.desc())
            )
            all_recent_payments = result.scalars().all()
            logger.warning(f"Gefundene Payments in letzten 5 Minuten: {len(all_recent_payments)}")

            # Versuche Payment über checkout_id zu finden (falls vorhanden)
            if checkout_id:
                for payment in all_recent_payments:
                    if payment.checkout_id == checkout_id:
                        sumup_payment = payment
                        logger.info(
                            f"Payment gefunden über Fallback-Suche (checkout_id): Payment ID {payment.id}"
                        )
                        break

            # Falls immer noch nicht gefunden, versuche über webhook_data.checkout_reference
            if not sumup_payment and checkout_reference:
                for payment in all_recent_payments:
                    if payment.webhook_data and isinstance(payment.webhook_data, dict):
                        stored_reference = payment.webhook_data.get("checkout_reference")
                        if stored_reference and stored_reference == checkout_reference:
                            sumup_payment = payment
                            logger.info(
                                f"Payment gefunden über Fallback-Suche (checkout_reference): Payment ID {payment.id}"
                            )
                            break

            # Falls immer noch nicht gefunden: Nimm das neueste Payment mit Status "processing" oder "pending"
            # (wahrscheinlich das, das gerade fehlgeschlagen ist)
            if not sumup_payment:
                for payment in all_recent_payments:
                    if payment.status in ["processing", "pending"]:
                        sumup_payment = payment
                        logger.info(
                            f"Payment gefunden über Fallback-Suche (neuestes processing Payment): Payment ID {payment.id}, Order ID {payment.order_id}, Status: {payment.status}"
                        )
                        break

        if not sumup_payment:
            logger.warning(
                f"SumUpPayment nicht gefunden für "
                f"client_transaction_id: {client_transaction_id}, "
                f"checkout_id: {checkout_id}, "
                f"checkout_reference: {checkout_reference}"
            )
            logger.warning(f"Event Type: {event_type}")
            logger.warning(
                f"Data object: {json.dumps(data, indent=2, default=str) if data else 'None'}"
            )
            logger.warning(
                f"Vollständiger Webhook-Payload: {json.dumps(webhook_data, indent=2, default=str)}"
            )
            return {"status": "ignored", "reason": "payment_not_found"}

        # Order laden
        order = await session.get(Order, sumup_payment.order_id)
        if not order:
            logger.error(f"Order nicht gefunden für payment_id: {sumup_payment.id}")
            return {"status": "error", "reason": "order_not_found"}

        # Event verarbeiten
        # Normalisiere Event-Type (SumUp verwendet verschiedene Formate)
        event_type_normalized = event_type.lower() if event_type else ""

        if event_type_normalized in ["payment.succeeded", "payment_succeeded"]:
            # Zahlung erfolgreich
            sumup_payment.status = "successful"
            sumup_payment.transaction_code = transaction_code
            sumup_payment.transaction_id = transaction_id
            # Aktualisiere checkout_id falls vorhanden
            if checkout_id and not sumup_payment.checkout_id:
                sumup_payment.checkout_id = checkout_id
            sumup_payment.completed_at = datetime.now(UTC)
            sumup_payment.webhook_data = webhook_data

            # Order als bezahlt markieren
            order.payment_status = "paid"
            order.payment_method = "sumup_card"
            order.paid_at = datetime.now(UTC)

            logger.info(f"Zahlung erfolgreich: Order {order.id}, Transaction {transaction_code}")

        elif event_type_normalized in ["payment.failed", "payment_failed"]:
            # Zahlung fehlgeschlagen
            sumup_payment.status = "failed"
            sumup_payment.completed_at = datetime.now(UTC)
            sumup_payment.webhook_data = webhook_data

            # Order bleibt unbezahlt
            logger.warning(
                f"Zahlung fehlgeschlagen: Order {order.id}, Transaction {transaction_code}"
            )

        elif event_type_normalized in ["payment.canceled", "payment_canceled"]:
            # Zahlung abgebrochen
            sumup_payment.status = "canceled"
            sumup_payment.completed_at = datetime.now(UTC)
            sumup_payment.webhook_data = webhook_data

            logger.info(f"Zahlung abgebrochen: Order {order.id}, Transaction {transaction_code}")

        elif event_type_normalized in [
            "checkout.status.updated",
            "checkout_status_changed",
            "checkout_status_updated",
        ]:
            # Checkout-Status wurde aktualisiert
            checkout_status = transaction_status or data.get("status", "").upper()

            # Aktualisiere checkout_id falls vorhanden
            if checkout_id and not sumup_payment.checkout_id:
                sumup_payment.checkout_id = checkout_id

            # Status basierend auf Checkout-Status aktualisieren
            if checkout_status == "PAID":
                sumup_payment.status = "successful"
                sumup_payment.transaction_code = transaction_code
                sumup_payment.transaction_id = transaction_id
                sumup_payment.completed_at = datetime.now(UTC)

                # Rufe vollständigen Receipt ab, um alle SumUp-Daten zu erhalten (TSE, Transaktionsdaten, etc.)
                receipt_data = None
                if (transaction_code or transaction_id) and SUMUP_MERCHANT_CODE and SUMUP_API_KEY:
                    try:
                        async with SumUpService(SUMUP_API_KEY) as sumup:
                            receipt = await sumup.get_receipt(
                                merchant_code=SUMUP_MERCHANT_CODE,
                                transaction_code=transaction_code,
                                transaction_id=transaction_id,
                            )
                            # Speichere vollständigen Receipt mit allen Daten
                            receipt_data = {
                                "transaction_data": receipt.get("transaction_data", {}),
                                "merchant_data": receipt.get("merchant_data", {}),
                                "emv_data": receipt.get("emv_data", {}),
                                "acquirer_data": receipt.get("acquirer_data", {}),
                            }

                            # Extrahiere wichtige Felder für einfachen Zugriff
                            transaction_data = receipt_data.get("transaction_data", {})
                            receipt_items = transaction_data.get("products")

                            if receipt_items:
                                logger.info(
                                    f"Receipt-Items gefunden: {len(receipt_items)} Produkte für Order {order.id}"
                                )

                            logger.info(
                                f"Vollständiger Receipt abgerufen für Order {order.id}: Transaction Code {transaction_code}, Receipt No: {transaction_data.get('receipt_no')}"
                            )

                            # Aktualisiere webhook_data mit vollständigem Receipt
                            if sumup_payment.webhook_data:
                                sumup_payment.webhook_data["receipt_data"] = receipt_data
                                if receipt_items:
                                    sumup_payment.webhook_data["receipt_items"] = receipt_items
                            else:
                                sumup_payment.webhook_data = {
                                    "receipt_data": receipt_data,
                                    "receipt_items": receipt_items if receipt_items else None,
                                }

                            # Aktualisiere auch SumUpPayment-Felder mit Receipt-Daten
                            if transaction_data.get("receipt_no"):
                                # Speichere Receipt Number falls vorhanden
                                if not sumup_payment.webhook_data:
                                    sumup_payment.webhook_data = {}
                                sumup_payment.webhook_data["receipt_no"] = transaction_data.get(
                                    "receipt_no"
                                )

                    except Exception as e:
                        logger.warning(
                            f"Fehler beim Abrufen des Receipts für Order {order.id}: {e}"
                        )
                        # Nicht kritisch - wir haben bereits die Items im webhook_data gespeichert

                # Order als bezahlt markieren
                order.payment_status = "paid"
                order.payment_method = "sumup_card"
                order.paid_at = datetime.now(UTC)

                logger.info(
                    f"Checkout erfolgreich bezahlt: Order {order.id}, Checkout {checkout_id}"
                )

            elif checkout_status == "FAILED":
                sumup_payment.status = "failed"
                sumup_payment.completed_at = datetime.now(UTC)
                logger.warning(f"Checkout fehlgeschlagen: Order {order.id}, Checkout {checkout_id}")

            elif checkout_status == "EXPIRED":
                sumup_payment.status = "canceled"
                sumup_payment.completed_at = datetime.now(UTC)
                logger.info(f"Checkout abgelaufen: Order {order.id}, Checkout {checkout_id}")

            # Webhook-Daten aktualisieren
            sumup_payment.webhook_data = webhook_data

        else:
            logger.warning(f"Unbekanntes Event-Type: {event_type}")
            # Speichere trotzdem die Webhook-Daten für Debugging
            sumup_payment.webhook_data = webhook_data
            await session.commit()
            return {"status": "ignored", "reason": f"unknown_event_type: {event_type}"}

        await session.commit()

        return {
            "status": "processed",
            "event_type": event_type,
            "order_id": order.id,
            "payment_id": sumup_payment.id,
        }

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in webhook: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")
    except Exception as e:
        logger.error(f"Error processing SumUp webhook: {e}", exc_info=True)
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing webhook: {str(e)}",
        )

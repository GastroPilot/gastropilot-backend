"""
SumUp Service für Terminal-Integration.

Verwaltet die Kommunikation mit der SumUp API für:
- Reader-Verwaltung (Terminals)
- Checkout-Erstellung
- Zahlungsstatus-Abfrage
- Webhook-Verarbeitung
"""
import logging
from typing import Optional, Dict, Any
import httpx
from datetime import datetime

logger = logging.getLogger(__name__)


class SumUpService:
    """Service für SumUp API-Interaktionen."""
    
    BASE_URL = "https://api.sumup.com"
    
    def __init__(self, api_key: str):
        """
        Initialisiert den SumUp Service.
        
        Args:
            api_key: SumUp API Key (sk_test_... oder sk_live_...)
        """
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def close(self):
        """Schließt den HTTP-Client."""
        await self.client.aclose()
    
    # Reader Management
    
    async def list_readers(self, merchant_code: str) -> list[Dict[str, Any]]:
        """
        Listet alle Reader (Terminals) für einen Merchant.
        
        Args:
            merchant_code: SumUp Merchant Code (z.B. "MH4H92C7")
            
        Returns:
            Liste von Reader-Objekten
        """
        try:
            response = await self.client.get(
                f"/v0.1/merchants/{merchant_code}/readers"
            )
            response.raise_for_status()
            data = response.json()
            return data.get("items", [])
        except httpx.HTTPStatusError as e:
            logger.error(f"SumUp API Error listing readers: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error listing SumUp readers: {e}")
            raise
    
    async def get_reader(self, merchant_code: str, reader_id: str) -> Dict[str, Any]:
        """
        Holt einen einzelnen Reader.
        
        Args:
            merchant_code: SumUp Merchant Code
            reader_id: Reader ID (z.B. "rdr_3MSAFM23CK82VSTT4BN6RWSQ65")
            
        Returns:
            Reader-Objekt
        """
        try:
            response = await self.client.get(
                f"/v0.1/merchants/{merchant_code}/readers/{reader_id}"
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"SumUp API Error getting reader: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error getting SumUp reader: {e}")
            raise
    
    async def create_reader(
        self,
        merchant_code: str,
        pairing_code: str,
        name: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Erstellt einen neuen Reader (paart ein Terminal).
        
        Args:
            merchant_code: SumUp Merchant Code
            pairing_code: 8-9 stelliger Pairing-Code vom Terminal
            name: Benutzerdefinierter Name für das Terminal
            metadata: Optionale Metadaten
            
        Returns:
            Reader-Objekt
        """
        try:
            payload = {
                "pairing_code": pairing_code,
                "name": name,
            }
            if metadata:
                payload["metadata"] = metadata
            
            response = await self.client.post(
                f"/v0.1/merchants/{merchant_code}/readers",
                json=payload
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"SumUp API Error creating reader: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error creating SumUp reader: {e}")
            raise
    
    async def get_reader_status(self, merchant_code: str, reader_id: str) -> Dict[str, Any]:
        """
        Holt den Status eines Readers (Batterie, Verbindung, aktueller Zustand).
        
        Args:
            merchant_code: SumUp Merchant Code
            reader_id: Reader ID
            
        Returns:
            Status-Objekt mit battery_level, status, state, etc.
        """
        try:
            response = await self.client.get(
                f"/v0.1/merchants/{merchant_code}/readers/{reader_id}/status"
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"SumUp API Error getting reader status: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error getting SumUp reader status: {e}")
            raise
    
    # Checkout Management
    
    async def create_checkout(
        self,
        merchant_code: str,
        amount: float,
        currency: str = "EUR",
        checkout_reference: Optional[str] = None,
        description: Optional[str] = None,
        return_url: Optional[str] = None,
        items: Optional[list[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Erstellt einen Checkout für eine Zahlung.
        
        Args:
            merchant_code: SumUp Merchant Code
            amount: Betrag (z.B. 10.50 für 10,50 EUR)
            currency: Währung (Standard: "EUR")
            checkout_reference: Eindeutige Referenz (optional)
            description: Beschreibung (optional)
            return_url: URL für Rückleitung nach Zahlung (optional)
            items: Liste von Bestellungspositionen (optional)
                  Format: [{"name": "...", "quantity": 1, "unit_price": 10.50, ...}]
            
        Returns:
            Checkout-Objekt
        """
        try:
            import uuid
            payload = {
                "checkout_reference": checkout_reference or str(uuid.uuid4()),
                "amount": amount,
                "currency": currency,
                "merchant_code": merchant_code,
            }
            if description:
                payload["description"] = description
            if return_url:
                payload["return_url"] = return_url
                logger.info(f"SumUp Checkout wird mit return_url erstellt: {return_url}")
            else:
                logger.warning("SumUp Checkout wird ohne return_url erstellt - Webhooks werden nicht empfangen!")
            
            # Items als metadata übergeben im SumUp Receipt-Format
            # SumUp erwartet: name, description, price (NETTO), quantity, total_price (NETTO)
            if items:
                # Konvertiere Items ins SumUp Receipt-Format
                receipt_items = []
                for item in items:
                    receipt_item = {
                        "name": item.get("name", ""),
                        "description": item.get("description", ""),
                        "price": item.get("price", item.get("unit_price", 0)),  # Netto-Preis
                        "quantity": item.get("quantity", 1),
                        "total_price": item.get("total_price", item.get("price", 0) * item.get("quantity", 1)),  # Netto-Gesamtpreis
                    }
                    receipt_items.append(receipt_item)
                
                # Versuche Items als metadata zu übergeben (für Receipt-Generierung)
                payload["metadata"] = {
                    "order_items": items,  # Original-Items für unsere interne Nachverfolgbarkeit
                    "products": receipt_items,  # SumUp Receipt-Format (name, description, price, quantity, total_price)
                }
                
                # Erweitere auch die description um Item-Details für bessere Lesbarkeit
                if description:
                    items_text = "\n".join([
                        f"- {item.get('name', 'Item')} x{item.get('quantity', 1)}: {item.get('unit_price', item.get('price', 0)):.2f} {currency}"
                        for item in items
                    ])
                    payload["description"] = f"{description}\n\nItems:\n{items_text}"
            
            response = await self.client.post(
                "/v0.1/checkouts",
                json=payload
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"SumUp API Error creating checkout: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error creating SumUp checkout: {e}")
            raise
    
    async def process_checkout(
        self,
        checkout_id: str,
        payment_type: str = "card",
        card: Optional[Dict[str, Any]] = None,
        installments: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Verarbeitet einen Checkout (komplettiert die Zahlung).
        
        Args:
            checkout_id: Checkout ID vom create_checkout
            payment_type: Zahlungsart (z.B. "card", "boleto", "ideal")
            card: Kartendaten (optional, falls payment_type="card")
            installments: Anzahl Raten (optional, z.B. für Brasilien)
            
        Returns:
            Checkout-Objekt mit aktualisiertem Status (PAID, FAILED, etc.)
        """
        try:
            payload = {
                "payment_type": payment_type,
            }
            
            if card:
                payload["card"] = card
            if installments:
                payload["installments"] = installments
            
            response = await self.client.put(
                f"/v0.1/checkouts/{checkout_id}",
                json=payload
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"SumUp API Error processing checkout: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error processing SumUp checkout: {e}")
            raise
    
    # Reader Checkout (Terminal Payment)
    
    async def create_merchant_checkout(
        self,
        merchant_code: str,
        amount: float,
        currency: str = "EUR",
        minor_unit: int = 2,
        description: Optional[str] = None,
        return_url: Optional[str] = None,
        tip_rates: Optional[list[float]] = None,
        tip_timeout: Optional[int] = None,
        installments: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Erstellt einen Checkout für einen Merchant (ohne Reader-ID).
        
        Args:
            merchant_code: SumUp Merchant Code
            amount: Betrag (z.B. 10.50)
            currency: Währung (Standard: "EUR")
            minor_unit: Anzahl Dezimalstellen (Standard: 2)
            description: Beschreibung
            return_url: Webhook URL für Zahlungsstatus
            tip_rates: Liste von Trinkgeld-Sätzen (z.B. [0.05, 0.10, 0.15])
            tip_timeout: Timeout für Trinkgeld-Auswahl in Sekunden (30-120)
            installments: Anzahl Raten (optional, z.B. für Brasilien)
            
        Returns:
            Response mit client_transaction_id
        """
        try:
            # Betrag in Minor Units umrechnen (z.B. 10.50 EUR -> 1050)
            value = int(amount * (10 ** minor_unit))
            
            payload = {
                "total_amount": {
                    "currency": currency,
                    "minor_unit": minor_unit,
                    "value": value,
                }
            }
            
            if description:
                payload["description"] = description
            if return_url:
                payload["return_url"] = return_url
            if tip_rates:
                payload["tip_rates"] = tip_rates
            if tip_timeout:
                payload["tip_timeout"] = tip_timeout
            if installments:
                payload["installments"] = installments
            
            response = await self.client.post(
                f"/v0.1/merchants/{merchant_code}/checkout",
                json=payload
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"SumUp API Error creating merchant checkout: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error creating SumUp merchant checkout: {e}")
            raise
    
    async def create_reader_checkout(
        self,
        merchant_code: str,
        reader_id: str,
        amount: float,
        currency: str = "EUR",
        minor_unit: int = 2,
        description: Optional[str] = None,
        return_url: Optional[str] = None,
        tip_rates: Optional[list[float]] = None,
        tip_timeout: Optional[int] = None,
        installments: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Erstellt einen Checkout für ein Terminal (Reader).
        
        Args:
            merchant_code: SumUp Merchant Code
            reader_id: Reader ID
            amount: Betrag (z.B. 10.50)
            currency: Währung (Standard: "EUR")
            minor_unit: Anzahl Dezimalstellen (Standard: 2)
            description: Beschreibung
            return_url: Webhook URL für Zahlungsstatus
            tip_rates: Liste von Trinkgeld-Sätzen (z.B. [0.05, 0.10, 0.15])
            tip_timeout: Timeout für Trinkgeld-Auswahl in Sekunden (30-120)
            installments: Anzahl Raten (optional, z.B. für Brasilien)
            
        Returns:
            Response mit client_transaction_id
        """
        try:
            # Betrag in Minor Units umrechnen (z.B. 10.50 EUR -> 1050)
            value = int(amount * (10 ** minor_unit))
            
            payload = {
                "total_amount": {
                    "currency": currency,
                    "minor_unit": minor_unit,
                    "value": value,
                }
            }
            
            if description:
                payload["description"] = description
            if return_url:
                payload["return_url"] = return_url
            if tip_rates:
                payload["tip_rates"] = tip_rates
            if tip_timeout:
                payload["tip_timeout"] = tip_timeout
            if installments:
                payload["installments"] = installments
            
            response = await self.client.post(
                f"/v0.1/merchants/{merchant_code}/readers/{reader_id}/checkout",
                json=payload
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"SumUp API Error creating reader checkout: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error creating SumUp reader checkout: {e}")
            raise
    
    async def terminate_reader_checkout(
        self,
        merchant_code: str,
        reader_id: str
    ) -> None:
        """
        Bricht einen laufenden Checkout am Terminal ab.
        
        Args:
            merchant_code: SumUp Merchant Code
            reader_id: Reader ID
        """
        try:
            response = await self.client.post(
                f"/v0.1/merchants/{merchant_code}/readers/{reader_id}/terminate"
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"SumUp API Error terminating reader checkout: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error terminating SumUp reader checkout: {e}")
            raise
    
    # Transaction Management
    
    async def get_transaction(
        self,
        merchant_code: str,
        transaction_code: Optional[str] = None,
        transaction_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Holt eine Transaktion.
        
        Args:
            merchant_code: SumUp Merchant Code
            transaction_code: Transaction Code (z.B. "TEENSK4W2K")
            transaction_id: Transaction ID (Alternative)
            
        Returns:
            Transaction-Objekt
        """
        try:
            params = {}
            if transaction_code:
                params["transaction_code"] = transaction_code
            elif transaction_id:
                params["id"] = transaction_id
            else:
                raise ValueError("Either transaction_code or transaction_id must be provided")
            
            response = await self.client.get(
                f"/v2.1/merchants/{merchant_code}/transactions",
                params=params
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"SumUp API Error getting transaction: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error getting SumUp transaction: {e}")
            raise
    
    async def get_receipt(
        self,
        merchant_code: str,
        transaction_code: Optional[str] = None,
        transaction_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ruft einen vollständigen Receipt für eine Transaktion ab.
        
        Der Receipt enthält alle verfügbaren SumUp-Daten:
        - transaction_data: Transaktionsdetails, Products (Line Items), VAT Rates, Card Info, etc.
        - merchant_data: Merchant-Informationen
        - emv_data: EMV/TSE-Daten (falls verfügbar)
        - acquirer_data: Terminal ID, Authorization Code, Return Code, etc.
        
        Args:
            merchant_code: SumUp Merchant Code
            transaction_code: Transaction Code (z.B. "TEENSK4W2K")
            transaction_id: Transaction ID (Alternative)
            
        Returns:
            Vollständiges Receipt-Objekt mit allen verfügbaren Daten
        """
        try:
            if not transaction_code and not transaction_id:
                raise ValueError("Either transaction_code or transaction_id must be provided")
            
            # SumUp Receipts API: GET /v1.1/receipts/{id}?mid={merchant_code}
            receipt_id = transaction_code or transaction_id
            
            params = {
                "mid": merchant_code,
            }
            
            response = await self.client.get(
                f"/v1.1/receipts/{receipt_id}",
                params=params
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"SumUp API Error getting receipt: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error getting SumUp receipt: {e}")
            raise

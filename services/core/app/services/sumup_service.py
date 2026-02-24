"""SumUp API integration service for prepayments and checkouts."""

from __future__ import annotations

import logging
import uuid

from httpx import AsyncClient, Timeout

logger = logging.getLogger(__name__)

SUMUP_BASE_URL = "https://api.sumup.com"


class SumUpService:
    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client: AsyncClient | None = None

    async def __aenter__(self):
        self._client = AsyncClient(
            base_url=SUMUP_BASE_URL,
            timeout=Timeout(30.0),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def close(self):
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> AsyncClient:
        if not self._client:
            self._client = AsyncClient(
                base_url=SUMUP_BASE_URL,
                timeout=Timeout(30.0),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    # --- Checkout Management ---

    async def create_checkout(
        self,
        merchant_code: str,
        amount: float,
        currency: str = "EUR",
        checkout_reference: str | None = None,
        description: str | None = None,
        return_url: str | None = None,
    ) -> dict:
        if not checkout_reference:
            checkout_reference = str(uuid.uuid4())

        payload: dict = {
            "amount": amount,
            "currency": currency,
            "merchant_code": merchant_code,
            "checkout_reference": checkout_reference,
        }
        if description:
            payload["description"] = description
        if return_url:
            payload["return_url"] = return_url

        try:
            response = await self.client.post("/v0.1/checkouts", json=payload)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to create SumUp checkout: {e}", exc_info=True)
            raise

    async def get_checkout_status(self, checkout_id: str) -> dict:
        try:
            response = await self.client.get(f"/v0.1/checkouts/{checkout_id}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get checkout status: {e}", exc_info=True)
            raise

    # --- Reader Management ---

    async def list_readers(self, merchant_code: str) -> list[dict]:
        try:
            response = await self.client.get(f"/v0.1/merchants/{merchant_code}/readers")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to list readers: {e}", exc_info=True)
            raise

    async def get_reader(self, merchant_code: str, reader_id: str) -> dict:
        try:
            response = await self.client.get(f"/v0.1/merchants/{merchant_code}/readers/{reader_id}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get reader: {e}", exc_info=True)
            raise

    async def create_reader(
        self, merchant_code: str, pairing_code: str, name: str, metadata: dict | None = None
    ) -> dict:
        payload: dict = {"pairing_code": pairing_code, "name": name}
        if metadata:
            payload["metadata"] = metadata
        try:
            response = await self.client.post(
                f"/v0.1/merchants/{merchant_code}/readers", json=payload
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to create reader: {e}", exc_info=True)
            raise

    async def get_reader_status(self, merchant_code: str, reader_id: str) -> dict:
        try:
            response = await self.client.get(
                f"/v0.1/merchants/{merchant_code}/readers/{reader_id}/status"
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get reader status: {e}", exc_info=True)
            raise

    # --- Reader Checkout ---

    async def create_reader_checkout(
        self,
        merchant_code: str,
        reader_id: str,
        amount: float,
        currency: str = "EUR",
        minor_unit: int = 2,
        description: str | None = None,
        return_url: str | None = None,
        tip_rates: list[float] | None = None,
        tip_timeout: int | None = None,
    ) -> dict:
        payload: dict = {
            "total_amount": {
                "currency": currency,
                "minor_unit": minor_unit,
                "value": int(amount * (10**minor_unit)),
            }
        }
        if description:
            payload["description"] = description
        if return_url:
            payload["return_url"] = return_url
        if tip_rates:
            payload["tip_rates"] = tip_rates
        if tip_timeout:
            payload["tip_timeout"] = max(30, min(120, tip_timeout))

        try:
            response = await self.client.post(
                f"/v0.1/merchants/{merchant_code}/readers/{reader_id}/checkout",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to create reader checkout: {e}", exc_info=True)
            raise

    async def terminate_reader_checkout(self, merchant_code: str, reader_id: str) -> None:
        try:
            response = await self.client.post(
                f"/v0.1/merchants/{merchant_code}/readers/{reader_id}/terminate"
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to terminate checkout: {e}", exc_info=True)
            raise

    # --- Transaction ---

    async def get_transaction(
        self,
        merchant_code: str,
        transaction_code: str | None = None,
        transaction_id: str | None = None,
    ) -> dict:
        params: dict = {}
        if transaction_code:
            params["transaction_code"] = transaction_code
        if transaction_id:
            params["transaction_id"] = transaction_id
        try:
            response = await self.client.get(
                f"/v2.1/merchants/{merchant_code}/transactions", params=params
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get transaction: {e}", exc_info=True)
            raise

    async def get_receipt(
        self,
        merchant_code: str,
        transaction_code: str | None = None,
        transaction_id: str | None = None,
    ) -> dict:
        tx_id = transaction_code or transaction_id
        try:
            response = await self.client.get(
                f"/v1.1/receipts/{tx_id}", params={"mid": merchant_code}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get receipt: {e}", exc_info=True)
            raise

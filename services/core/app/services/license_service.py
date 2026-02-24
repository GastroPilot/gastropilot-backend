"""
License Service - Kommunikation mit Mutterschiff für Feature-Freischaltungen.
Portiert vom Legacy-Monolith, angepasst für Core-Service-Architektur.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from httpx import AsyncClient, Timeout

from app.core.config import settings

logger = logging.getLogger(__name__)

ALL_MODULES = [
    "reservations_module",
    "orders_module",
    "web_reservation_module",
    "whatsapp_bot_module",
    "phone_bot_module",
]

DEFAULT_FEATURES: dict[str, bool] = {module: False for module in ALL_MODULES}
DEVELOPMENT_FEATURES: dict[str, bool] = {module: True for module in ALL_MODULES}


class LicenseService:
    def __init__(self):
        self._features: dict[str, bool] = DEVELOPMENT_FEATURES.copy()
        self._package: str | None = None
        self._customer_number: str | None = None
        self._customer_name: str | None = None
        self._last_check: datetime | None = None
        self._check_lock = asyncio.Lock()
        self._initialized = False
        self._consecutive_failures = 0
        self._max_consecutive_failures = 3
        self._fallback_features: dict[str, bool] = {}

    async def check_license(self, force: bool = False) -> dict[str, bool]:
        async with self._check_lock:
            license_key = getattr(settings, "LICENSE_KEY", None)
            mothership_url = getattr(settings, "MOTHERSHIP_URL", None)
            mothership_api_key = getattr(settings, "MOTHERSHIP_API_KEY", None)
            check_interval = getattr(settings, "LICENSE_CHECK_INTERVAL", 300)
            check_timeout = getattr(settings, "LICENSE_CHECK_TIMEOUT", 10)

            if not force and self._last_check:
                elapsed = (datetime.now(UTC) - self._last_check).total_seconds()
                if elapsed < check_interval:
                    return self._features.copy()

            if not license_key:
                logger.warning("LICENSE_KEY not set - using default features (all enabled)")
                self._features = DEVELOPMENT_FEATURES.copy()
                self._package = "development"
                self._last_check = datetime.now(UTC)
                self._initialized = True
                return self._features.copy()

            if self._consecutive_failures >= self._max_consecutive_failures:
                if self._fallback_features:
                    return self._fallback_features.copy()
                return self._features.copy()

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if attempt > 0:
                        await asyncio.sleep(2 ** (attempt - 1))

                    async with AsyncClient(timeout=Timeout(check_timeout)) as client:
                        headers = {}
                        if mothership_api_key:
                            headers["X-API-Key"] = mothership_api_key

                        response = await client.get(
                            f"{mothership_url}/v1/license/check",
                            params={"license_key": license_key},
                            headers=headers,
                        )

                        if response.status_code == 200:
                            data = response.json()

                            if not data.get("valid", False):
                                self._features = DEFAULT_FEATURES.copy()
                                self._package = None
                                self._consecutive_failures += 1
                                if self._initialized and not self._fallback_features:
                                    self._fallback_features = self._features.copy()
                            else:
                                features_from_server = data.get("features", {})
                                new_features = DEFAULT_FEATURES.copy()
                                for module in ALL_MODULES:
                                    new_features[module] = features_from_server.get(module, False)

                                self._package = data.get("package")
                                self._customer_number = data.get("customer_number")
                                self._customer_name = data.get("customer_name")
                                self._fallback_features = new_features.copy()
                                self._features = new_features
                                self._consecutive_failures = 0

                            self._last_check = datetime.now(UTC)
                            self._initialized = True
                            return self._features.copy()
                        else:
                            if response.status_code >= 500 and attempt < max_retries - 1:
                                continue
                            break

                except (TimeoutError, ConnectionError):
                    if attempt < max_retries - 1:
                        continue
                    break
                except Exception:
                    logger.error("Error during license check", exc_info=True)
                    if attempt >= max_retries - 1:
                        break

            self._consecutive_failures += 1
            if self._fallback_features:
                return self._fallback_features.copy()
            if not self._initialized:
                self._features = DEFAULT_FEATURES.copy()
                self._initialized = True
            return self._features.copy()

    def get_features(self) -> dict[str, bool]:
        return self._features.copy()

    def get_package(self) -> str | None:
        return self._package

    def get_customer_info(self) -> dict[str, str | None]:
        return {
            "customer_number": self._customer_number,
            "customer_name": self._customer_name,
            "package": self._package,
        }

    def is_feature_enabled(self, feature: str) -> bool:
        return self._features.get(feature, False)

    def has_reservations_module(self) -> bool:
        return self.is_feature_enabled("reservations_module")

    def has_orders_module(self) -> bool:
        return self.is_feature_enabled("orders_module")

    def has_web_reservation_module(self) -> bool:
        return self.is_feature_enabled("web_reservation_module")

    def has_whatsapp_bot_module(self) -> bool:
        return self.is_feature_enabled("whatsapp_bot_module")

    def has_phone_bot_module(self) -> bool:
        return self.is_feature_enabled("phone_bot_module")

    async def ensure_initialized(self):
        if not self._initialized:
            await self.check_license(force=True)


license_service = LicenseService()

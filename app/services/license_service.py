"""
License Service - Kommunikation mit Mutterschiff für Feature-Freischaltungen
"""
import logging
import asyncio
from typing import Dict, Optional
from datetime import datetime, timezone
from httpx import AsyncClient, Timeout
from app.settings import LICENSE_KEY, MOTHERSHIP_URL, LICENSE_CHECK_INTERVAL, LICENSE_CHECK_TIMEOUT

logger = logging.getLogger(__name__)


# Alle verfügbaren Module
ALL_MODULES = [
    "reservations_module",
    "orders_module",
    "web_reservation_module",
    "whatsapp_bot_module",
    "phone_bot_module",
]

# Default-Features (alle deaktiviert)
DEFAULT_FEATURES: Dict[str, bool] = {module: False for module in ALL_MODULES}

# Development-Features (alle aktiviert)
DEVELOPMENT_FEATURES: Dict[str, bool] = {module: True for module in ALL_MODULES}


class LicenseService:
    """Service zur Verwaltung von Lizenzen und Feature-Flags."""
    
    def __init__(self):
        self._features: Dict[str, bool] = DEVELOPMENT_FEATURES.copy()  # Default: alle aktiviert (für Development)
        self._package: Optional[str] = None  # Paket-Name (starter, basic, professional, business, premium)
        self._customer_number: Optional[str] = None
        self._customer_name: Optional[str] = None
        self._last_check: Optional[datetime] = None
        self._check_lock = asyncio.Lock()
        self._initialized = False
        self._consecutive_failures = 0
        self._max_consecutive_failures = 3
        self._fallback_features: Dict[str, bool] = {}  # Fallback bei mehreren Fehlern
    
    async def check_license(self, force: bool = False) -> Dict[str, bool]:
        """
        Prüft die Lizenz beim Mutterschiff und aktualisiert die Feature-Flags.
        
        Args:
            force: Wenn True, wird die Prüfung auch durchgeführt, wenn sie kürzlich stattfand.
        
        Returns:
            Dict mit Feature-Flags
        """
        async with self._check_lock:
            # Prüfe, ob ein Check nötig ist
            if not force and self._last_check:
                elapsed = (datetime.now(timezone.utc) - self._last_check).total_seconds()
                if elapsed < LICENSE_CHECK_INTERVAL:
                    logger.debug(f"License check skipped (last check was {elapsed:.0f}s ago)")
                    return self._features.copy()
            
            # Wenn kein License Key gesetzt ist, verwende Defaults (Development)
            if not LICENSE_KEY:
                logger.warning("LICENSE_KEY not set - using default features (all enabled)")
                self._features = DEVELOPMENT_FEATURES.copy()
                self._package = "development"
                self._last_check = datetime.now(timezone.utc)
                self._initialized = True
                return self._features.copy()
            
            # Prüfe ob zu viele aufeinanderfolgende Fehler (Grace Period)
            if self._consecutive_failures >= self._max_consecutive_failures:
                if self._fallback_features:
                    logger.warning(
                        f"Mutterschiff unavailable ({self._consecutive_failures} consecutive failures), "
                        f"using fallback features: {self._fallback_features}"
                    )
                    return self._fallback_features.copy()
                else:
                    logger.warning(
                        f"Mutterschiff unavailable ({self._consecutive_failures} consecutive failures), "
                        f"no fallback available, using cached features"
                    )
                    return self._features.copy()
            
            # Retry-Logik mit Exponential Backoff
            max_retries = 3
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    # Exponential Backoff: Warte vor Retry (außer beim ersten Versuch)
                    if attempt > 0:
                        wait_time = 2 ** (attempt - 1)  # 1s, 2s, 4s, ...
                        logger.info(f"Retrying license check (attempt {attempt + 1}/{max_retries}) after {wait_time}s...")
                        await asyncio.sleep(wait_time)
                    
                    # Kommunikation mit Mutterschiff
                    async with AsyncClient(timeout=Timeout(LICENSE_CHECK_TIMEOUT)) as client:
                        response = await client.get(
                            f"{MOTHERSHIP_URL}/v1/license/check",
                            params={
                                "license_key": LICENSE_KEY,
                            }
                        )
                        
                        if response.status_code == 200:
                            data = response.json()
                            
                            # Detaillierte Fehlerbehandlung basierend auf Response
                            if not data.get("valid", False):
                                error_message = data.get("message", "License invalid")
                                logger.warning(f"License check returned invalid license: {error_message}")
                                
                                # Bei ungültiger Lizenz: Features deaktivieren
                                self._features = DEFAULT_FEATURES.copy()
                                self._package = None
                                self._consecutive_failures += 1
                                
                                # Wenn bereits initialisiert, behalte alte Features als Fallback
                                if self._initialized and not self._fallback_features:
                                    self._fallback_features = self._features.copy()
                            else:
                                # Erfolgreicher Check - alle Module aus Response auslesen
                                features_from_server = data.get("features", {})
                                new_features = DEFAULT_FEATURES.copy()
                                for module in ALL_MODULES:
                                    new_features[module] = features_from_server.get(module, False)
                                
                                # Paket und Kundeninfo speichern
                                self._package = data.get("package")
                                self._customer_number = data.get("customer_number")
                                self._customer_name = data.get("customer_name")
                                
                                # Speichere als Fallback
                                self._fallback_features = new_features.copy()
                                
                                # Aktualisiere Features
                                self._features = new_features
                                self._consecutive_failures = 0  # Reset bei Erfolg
                            
                            self._last_check = datetime.now(timezone.utc)
                            self._initialized = True
                            logger.info(f"License check successful: {self._features}")
                            return self._features.copy()
                        else:
                            # HTTP-Fehler
                            error_text = response.text[:200]  # Limitiere Text-Länge
                            logger.warning(
                                f"License check failed with status {response.status_code}: {error_text}"
                            )
                            last_exception = Exception(f"HTTP {response.status_code}: {error_text}")
                            
                            # Retry bei 5xx Fehlern, nicht bei 4xx
                            if response.status_code >= 500 and attempt < max_retries - 1:
                                continue
                            else:
                                # Bei 4xx Fehlern oder nach letztem Retry: Fallback
                                break
                            
                except Exception as e:
                    last_exception = e
                    error_type = type(e).__name__
                    
                    # Retry bei Timeout/Connection Errors
                    if isinstance(e, (TimeoutError, ConnectionError)) and attempt < max_retries - 1:
                        logger.warning(f"Connection error during license check ({error_type}), will retry: {e}")
                        continue
                    else:
                        logger.error(f"Error during license check ({error_type}): {e}", exc_info=True)
                        if attempt >= max_retries - 1:
                            break
            
            # Alle Retries fehlgeschlagen
            self._consecutive_failures += 1
            logger.error(
                f"License check failed after {max_retries} attempts. "
                f"Consecutive failures: {self._consecutive_failures}/{self._max_consecutive_failures}"
            )
            
            # Bei Fehler: Verwende Fallback oder Cache
            if self._fallback_features:
                logger.info(f"Using fallback features: {self._fallback_features}")
                return self._fallback_features.copy()
            elif not self._initialized:
                # Beim ersten Check: Features deaktivieren
                self._features = DEFAULT_FEATURES.copy()
                self._initialized = True
            else:
                # Bei wiederholten Fehlern: Verwende bisherige Features (Grace Period)
                logger.warning("Using cached features due to mutterschiff unavailability")
            
            return self._features.copy()
    
    def get_features(self) -> Dict[str, bool]:
        """Gibt die aktuellen Feature-Flags zurück (ohne Check)."""
        return self._features.copy()
    
    def get_package(self) -> Optional[str]:
        """Gibt das aktuelle Paket zurück (ohne Check)."""
        return self._package
    
    def get_customer_info(self) -> Dict[str, Optional[str]]:
        """Gibt Kundeninformationen zurück."""
        return {
            "customer_number": self._customer_number,
            "customer_name": self._customer_name,
            "package": self._package,
        }
    
    def is_feature_enabled(self, feature: str) -> bool:
        """Prüft, ob ein Feature aktiviert ist."""
        return self._features.get(feature, False)
    
    def has_reservations_module(self) -> bool:
        """Prüft, ob das Reservierungsmodul aktiviert ist."""
        return self.is_feature_enabled("reservations_module")
    
    def has_orders_module(self) -> bool:
        """Prüft, ob das Bestellungs-/Menümodul aktiviert ist."""
        return self.is_feature_enabled("orders_module")
    
    def has_web_reservation_module(self) -> bool:
        """Prüft, ob das Web-Reservierungsformular aktiviert ist."""
        return self.is_feature_enabled("web_reservation_module")
    
    def has_whatsapp_bot_module(self) -> bool:
        """Prüft, ob der WhatsApp-Reservierungsbot aktiviert ist."""
        return self.is_feature_enabled("whatsapp_bot_module")
    
    def has_phone_bot_module(self) -> bool:
        """Prüft, ob der Telefon-Reservierungsbot aktiviert ist."""
        return self.is_feature_enabled("phone_bot_module")
    
    async def ensure_initialized(self):
        """Stellt sicher, dass die Features initialisiert sind."""
        if not self._initialized:
            await self.check_license(force=True)


# Globale Instanz
license_service = LicenseService()


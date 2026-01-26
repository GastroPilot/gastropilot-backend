"""
Middleware für Logging, Security Headers und Request Handling
"""
import logging
import time
import json
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from logging.handlers import TimedRotatingFileHandler
from pythonjsonlogger import jsonlogger
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth import verify_token
from app.database.instance import async_session
from app.database.models import User
from app.services.activity_logger import create_activity_log
from app.services.audit_logger import create_audit_log
from sqlalchemy import select
from app.settings import (
    LOG_LEVEL,
    LOG_FORMAT,
    LOG_DIR,
    LOG_FILE_NAME,
    LOG_BACKUP_COUNT,
    LOG_MAX_TOTAL_BYTES,
    ALLOWED_HOSTS,
    REQUEST_TIMEOUT,
    ENV,
    ACTIVITY_LOGGING_ENABLED,
)


# ==================== LOGGING SETUP ====================

class JSONFormatter(jsonlogger.JsonFormatter):
    """Custom JSON Formatter mit zusätzlichen Informationen"""
    def add_fields(self, log_record, record, message_dict):
        super(JSONFormatter, self).add_fields(log_record, record, message_dict)
        log_record['timestamp'] = datetime.now(timezone.utc).isoformat()
        log_record['level'] = record.levelname
        log_record['logger'] = record.name


class ColoredConsoleFormatter(logging.Formatter):
    """Farbiger Formatter für Console-Ausgabe mit strukturierter Darstellung"""
    
    # Prüfe ob Terminal Farben unterstützt
    _supports_color = sys.stdout.isatty() if hasattr(sys.stdout, 'isatty') else True
    
    # ANSI Farbcodes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Grün
        'WARNING': '\033[33m',    # Gelb
        'ERROR': '\033[31m',      # Rot
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m',       # Reset
        'BOLD': '\033[1m',
        'DIM': '\033[2m',
    }
    
    # Method-Farben
    METHOD_COLORS = {
        'GET': '\033[94m',        # Hellblau
        'POST': '\033[92m',       # Hellgrün
        'PUT': '\033[93m',        # Gelb
        'PATCH': '\033[96m',      # Cyan
        'DELETE': '\033[91m',     # Hellrot
        'OPTIONS': '\033[90m',    # Grau
    }
    
    # Status-Code Farben
    STATUS_COLORS = {
        '2xx': '\033[92m',        # Grün für Erfolg
        '3xx': '\033[94m',        # Blau für Weiterleitung
        '4xx': '\033[93m',        # Gelb für Client-Fehler
        '5xx': '\033[91m',        # Rot für Server-Fehler
    }
    
    def format(self, record: logging.LogRecord) -> str:
        """Formatiert Log-Einträge mit Farben und Struktur"""
        # Farben nur verwenden wenn Terminal unterstützt
        use_colors = self._supports_color
        
        # Basis-Formatierung
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
        level = record.levelname
        level_color = self.COLORS.get(level, '') if use_colors else ''
        reset = self.COLORS['RESET'] if use_colors else ''
        bold = self.COLORS['BOLD'] if use_colors else ''
        dim = self.COLORS['DIM'] if use_colors else ''
        
        # Message formatieren
        message = record.getMessage()
        
        # Extra-Felder für strukturierte Ausgabe
        extras = {}
        if hasattr(record, 'request_id'):
            extras['request_id'] = record.request_id
        if hasattr(record, 'method'):
            extras['method'] = record.method
        if hasattr(record, 'path'):
            extras['path'] = record.path
        if hasattr(record, 'status_code'):
            extras['status_code'] = record.status_code
        if hasattr(record, 'duration_ms'):
            extras['duration_ms'] = record.duration_ms
        if hasattr(record, 'client'):
            extras['client'] = record.client
        if hasattr(record, 'user_id'):
            extras['user_id'] = record.user_id
        if hasattr(record, 'user_name'):
            extras['user_name'] = record.user_name
        
        # Spezielle Formatierung für Request-Logs
        if 'method' in extras and 'path' in extras:
            method = extras['method']
            path = extras['path']
            method_color = (self.METHOD_COLORS.get(method, '') if use_colors else '')
            
            # Status-Code mit Farbe
            status_str = ""
            if 'status_code' in extras:
                status_code = extras['status_code']
                if use_colors:
                    if 200 <= status_code < 300:
                        status_color = self.STATUS_COLORS['2xx']
                    elif 300 <= status_code < 400:
                        status_color = self.STATUS_COLORS['3xx']
                    elif 400 <= status_code < 500:
                        status_color = self.STATUS_COLORS['4xx']
                    else:
                        status_color = self.STATUS_COLORS['5xx']
                    status_str = f" {status_color}{status_code}{reset}"
                else:
                    status_str = f" {status_code}"
            
            # Duration
            duration_str = ""
            if 'duration_ms' in extras:
                duration = float(extras['duration_ms'])
                if use_colors:
                    if duration < 100:
                        duration_color = '\033[92m'  # Grün für schnell
                    elif duration < 500:
                        duration_color = '\033[93m'   # Gelb für mittel
                    else:
                        duration_color = '\033[91m'   # Rot für langsam
                    duration_str = f" {duration_color}{duration:.0f}ms{reset}"
                else:
                    duration_str = f" {duration:.0f}ms"
            
            # User ID und vollständiger Name (nur wenn vorhanden)
            user_str = ""
            if 'user_id' in extras and extras['user_id']:
                if 'user_name' in extras and extras['user_name']:
                    user_str = f" {dim}{extras['user_name']}, User ID: {extras['user_id']}{reset}"
                else:
                    user_str = f" {dim}User ID: {extras['user_id']}{reset}"
            
            # Kompakte Formatierung
            formatted = (
                f"{dim}{timestamp}{reset} "
                f"{level_color}{level:7s}{reset} "
                f"{method_color}{method:6s}{reset} "
                f"{bold}{path[:50]}{reset}"  # Pfad auf 50 Zeichen begrenzen
                f"{status_str}"
                f"{duration_str}"
                f"{user_str}"
            )
            
            # Query-Parameter nur wenn vorhanden und kurz
            if hasattr(record, 'query') and record.query:
                query_short = record.query[:30] + "..." if len(record.query) > 30 else record.query
                formatted += f" {dim}?{query_short}{reset}"
            
            return formatted
        
        # Standard-Formatierung für andere Logs
        # Uvicorn-Logs haben oft "INFO: " am Anfang - entferne das für bessere Formatierung
        clean_message = message
        if message.startswith(f"{level}: "):
            clean_message = message[len(f"{level}: "):]
        elif ":" in message and message.split(":")[0] == level:
            clean_message = ":".join(message.split(":")[1:]).strip()
        
        formatted = (
            f"{dim}{timestamp}{reset} "
            f"{level_color}{level:7s}{reset} "
            f"{clean_message}"
        )
        
        # Extra-Felder hinzufügen
        if extras:
            extra_str = " ".join([f"{k}={v}" for k, v in extras.items()])
            formatted += f" {dim}({extra_str}){reset}"
        
        return formatted


def setup_logging():
    """Konfiguriert Logging: Console immer farbig, Datei immer JSON"""
    root_logger = logging.getLogger()
    if getattr(root_logger, "_gastropilot_configured", False):
        return root_logger

    root_logger.setLevel(LOG_LEVEL)
    
    # Console Handler - IMMER farbig für bessere Lesbarkeit
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = ColoredConsoleFormatter()
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File Handler (rotating) - IMMER JSON für bessere Parsbarkeit
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = DatePrefixedTimedRotatingFileHandler(
        LOG_FILE_NAME,
        LOG_DIR,
        when="midnight",
        interval=1,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
        max_total_bytes=LOG_MAX_TOTAL_BYTES,
    )
    
    # File-Handler bekommt immer JSON-Format (unabhängig von LOG_FORMAT)
    file_formatter = JSONFormatter('%(timestamp)s %(level)s %(name)s %(message)s')
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Uvicorn Access-Logging deaktivieren (wir haben eigenes Request-Logging)
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.setLevel(logging.WARNING)  # Nur Warnings und Errors
    uvicorn_access.propagate = False  # Verhindert Weiterleitung an Root-Logger
    uvicorn_access.handlers = []  # Entferne alle Handler
    
    # Uvicorn Standard-Logs - nur Warnings/Errors, keine Info-Logs
    # (Wir haben unsere eigenen Startup-Logs)
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.setLevel(logging.WARNING)  # Nur Warnings und Errors
    uvicorn_logger.handlers = []  # Entferne alle Handler
    uvicorn_logger.propagate = True  # Lasse Warnings/Errors durch unser System laufen
    
    # Uvicorn Error-Logs durch unser System
    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.handlers = []
    uvicorn_error.propagate = True

    root_logger._gastropilot_configured = True
    return root_logger


logger = logging.getLogger(__name__)


# ==================== MIDDLEWARE ====================


def _prune_logs(log_dir: Path, base_name: str, max_files: int, max_total_bytes: int) -> None:
    """
    Entfernt älteste Logfiles, wenn Anzahl oder Gesamtgröße Limits überschreiten.
    FIFO: Wir löschen die ältesten Dateien zuerst und lassen mindestens eine übrig.
    """
    log_files = sorted(
        [p for p in log_dir.glob(f"*{base_name}*") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
    )

    # 1) Anzahl begrenzen
    while max_files > 0 and len(log_files) > max_files:
        oldest = log_files.pop(0)
        try:
            oldest.unlink()
            logger.info(
                "Removed old log file to enforce retention count",
                extra={"file": str(oldest), "max_files": max_files},
            )
        except FileNotFoundError:
            continue
        except Exception:
            logger.exception(
                "Failed to remove old log file during count-based cleanup",
                extra={"file": str(oldest)},
            )
            break

    # 2) Gesamtgröße begrenzen
    total_size = sum(p.stat().st_size for p in log_files)
    while total_size > max_total_bytes and len(log_files) > 1:
        oldest = log_files.pop(0)
        try:
            size = oldest.stat().st_size
            oldest.unlink()
            total_size -= size
            logger.info(
                "Removed old log file to enforce log dir size limit",
                extra={"file": str(oldest), "max_total_bytes": max_total_bytes},
            )
        except FileNotFoundError:
            continue
        except Exception:
            logger.exception(
                "Failed to remove old log file during log dir cleanup",
                extra={"file": str(oldest)},
            )
            break


class DatePrefixedTimedRotatingFileHandler(TimedRotatingFileHandler):
    """Schreibt in ein tagesdatiertes Logfile und rotiert täglich (plus FIFO-Pruning)."""

    def __init__(
        self,
        base_name: str,
        log_dir: Path,
        when="midnight",
        interval=1,
        backupCount=0,
        encoding=None,
        delay=False,
        utc=False,
        max_total_bytes: int = LOG_MAX_TOTAL_BYTES,
    ):
        self.log_dir = log_dir
        self.base_name = base_name
        self.max_total_bytes = max_total_bytes
        log_dir.mkdir(parents=True, exist_ok=True)
        super().__init__(
            filename=self._build_filename(),
            when=when,
            interval=interval,
            backupCount=backupCount,
            encoding=encoding,
            delay=delay,
            utc=utc,
        )
        _prune_logs(self.log_dir, self.base_name, backupCount, self.max_total_bytes)

    def _build_filename(self) -> str:
        date_prefix = datetime.now().strftime("%d-%m-%Y")
        return str(self.log_dir / f"{date_prefix}_{self.base_name}")

    def doRollover(self):
        if self.stream:
            self.stream.close()
            self.stream = None

        current_time = int(time.time())
        # neues Tagesfile öffnen
        self.baseFilename = self._build_filename()
        self.stream = self._open()

        new_rollover = self.computeRollover(current_time)
        while new_rollover <= current_time:
            new_rollover += self.interval
        self.rolloverAt = new_rollover

        try:
            _prune_logs(self.log_dir, self.base_name, self.backupCount, self.max_total_bytes)
        except Exception:
            logging.getLogger(__name__).exception("Failed to enforce log retention after rollover")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware für Sicherheits-Header"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # Security Headers
        
        # X-Content-Type-Options: Verhindert MIME-Type Sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # X-Frame-Options: Verhindert Clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        
        # X-XSS-Protection: Aktiviert XSS-Filter im Browser
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Strict-Transport-Security: Erzwingt HTTPS-Verbindungen
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        
        # Referrer-Policy: Kontrolliert, welche Referrer-Informationen gesendet werden
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Permissions-Policy: Deaktiviert Browser-Features für erhöhte Sicherheit
        # Erweitert um weitere Features, die standardmäßig deaktiviert werden sollten
        response.headers["Permissions-Policy"] = (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            "payment=(), "
            "usb=(), "
            "magnetometer=(), "
            "gyroscope=(), "
            "accelerometer=(), "
            "ambient-light-sensor=(), "
            "autoplay=(), "
            "encrypted-media=(), "
            "fullscreen=(self), "
            "picture-in-picture=()"
        )

        # Content-Security-Policy (CSP): Definiert erlaubte Ressourcen-Quellen
        # Unterschiedliche Policies für Development und Production
        if ENV == "development":
            csp = (
                "default-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "font-src 'self' https://cdn.jsdelivr.net; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            )
        else:
            csp = (
                "default-src 'self'; "
                "style-src 'self'; "
                "script-src 'self'; "
                "img-src 'self' data:; "
                "font-src 'self'; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'; "
                "object-src 'none'; "
                "upgrade-insecure-requests"
            )
        response.headers["Content-Security-Policy"] = csp

        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware für Request/Response Logging - kompakt und übersichtlich"""
    
    # Endpunkte die nicht geloggt werden sollen
    IGNORED_PATHS = {
        "/api/v1/health",
        "/api/v1/",
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
        "/favicon.ico",
    }
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Ignoriere bestimmte Endpunkte
        if request.url.path in self.IGNORED_PATHS or request.method == "OPTIONS":
            return await call_next(request)
        
        start_time = time.time()
        
        # User-Informationen extrahieren (falls vorhanden)
        user_id = None
        user_name = None
        try:
            auth_header = request.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header.split(" ", 1)[1]
                payload = verify_token(token, token_type="access")
                if payload:
                    user_id = payload.get("user_id") or payload.get("sub")
        except Exception:
            pass  # Nicht authentifiziert oder Token ungültig
        
        # Request verarbeiten
        try:
            response = await call_next(request)
        except Exception as exc:
            process_time = time.time() - start_time
            # Fehler immer loggen
            log_record = logging.LogRecord(
                name=logger.name,
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg=str(exc)[:100],  # Erste 100 Zeichen
                args=(),
                exc_info=exc
            )
            log_record.method = request.method
            log_record.path = request.url.path
            log_record.status_code = 500
            log_record.duration_ms = f"{process_time*1000:.2f}"
            log_record.user_id = user_id
            # Vollständigen Namen aus DB holen, wenn user_id vorhanden ist
            if user_id:
                try:
                    async with async_session() as session:
                        result = await session.execute(
                            select(User.first_name, User.last_name).where(User.id == user_id)
                        )
                        user = result.first()
                        if user:
                            # Kombiniere first_name und last_name
                            full_name = f"{user.first_name} {user.last_name}".strip()
                            if full_name:
                                log_record.user_name = full_name
                except Exception:
                    pass
            logger.handle(log_record)
            raise
        
        process_time = time.time() - start_time
        
        # Nur Fehler oder langsame Requests loggen (oder wenn explizit gewünscht)
        status_code = response.status_code
        duration_ms = process_time * 1000
        
        # Logge nur:
        # - Fehler (4xx, 5xx)
        # - Langsame Requests (>500ms)
        # - POST/PUT/PATCH/DELETE (wichtige Aktionen)
        should_log = (
            status_code >= 400 or  # Fehler
            duration_ms > 500 or   # Langsam
            request.method in {"POST", "PUT", "PATCH", "DELETE"}  # Mutierende Requests
        )
        
        if should_log:
            # Vollständigen Namen aus DB holen, wenn user_id vorhanden ist
            if user_id:
                try:
                    async with async_session() as session:
                        result = await session.execute(
                            select(User.first_name, User.last_name).where(User.id == user_id)
                        )
                        user = result.first()
                        if user:
                            # Kombiniere first_name und last_name
                            full_name = f"{user.first_name} {user.last_name}".strip()
                            if full_name:
                                user_name = full_name
                except Exception:
                    pass  # Fehler beim Holen des Users ignorieren
            
            log_record = logging.LogRecord(
                name=logger.name,
                level=logging.WARNING if status_code >= 400 else logging.INFO,
                pathname="",
                lineno=0,
                msg="",  # Leer, da alles in den Extras steht
                args=(),
                exc_info=None
            )
            log_record.method = request.method
            log_record.path = request.url.path
            log_record.status_code = status_code
            log_record.duration_ms = f"{duration_ms:.2f}"
            log_record.user_id = user_id
            log_record.user_name = user_name
            # Query nur wenn vorhanden
            if request.url.query:
                log_record.query = request.url.query
            logger.handle(log_record)
        
        # Response-Header setzen
        response.headers["X-Process-Time"] = f"{process_time:.3f}"
        
        return response


class ActivityLogMiddleware(BaseHTTPMiddleware):
    """Schreibt Activity-Logs für mutierende Requests in die DB."""

    MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        if request.method not in self.MUTATING_METHODS:
            return response

        # Best-effort Logging, darf die Response nicht beeinflussen
        try:
            auth_header = request.headers.get("authorization") or ""
            token = auth_header.split(" ", 1)[1] if auth_header.lower().startswith("bearer ") else None
            user_id = None
            if token:
                payload = verify_token(token, token_type="access")
                if payload:
                    user_id = payload.get("user_id") or payload.get("sub")

            client_ip = request.client.host if request.client else None
            action = f"{request.method} {request.url.path} -> {response.status_code}"

            async with async_session() as session:
                await create_activity_log(
                    session,
                    action=action,
                    user_id=int(user_id) if user_id is not None else None,
                    ip_address=client_ip,
                    use_own_transaction=True,
                )
        except Exception:
            logger.exception(
                "Failed to write activity log",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                },
            )

        return response


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Schreibt einfache Audit-Logs für mutierende Requests (ohne Feld-Diffs)."""

    MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            body_bytes = await request.body()
            request._body = body_bytes  # type: ignore[attr-defined]
        except Exception:
            body_bytes = b""

        response = await call_next(request)

        if request.method not in self.MUTATING_METHODS:
            return response

        try:
            auth_header = request.headers.get("authorization") or ""
            token = auth_header.split(" ", 1)[1] if auth_header.lower().startswith("bearer ") else None
            user_id = None
            if token:
                payload = verify_token(token, token_type="access")
                if payload:
                    raw_user_id = payload.get("user_id") or payload.get("sub")
                    try:
                        user_id = int(raw_user_id) if raw_user_id is not None else None
                    except Exception:
                        user_id = None

            path_parts = request.url.path.strip("/").split("/")
            restaurant_id = None
            reservation_id = None
            try:
                if "restaurants" in path_parts:
                    idx = path_parts.index("restaurants")
                    if len(path_parts) > idx + 1 and path_parts[idx + 1].isdigit():
                        restaurant_id = int(path_parts[idx + 1])
                if "reservations" in path_parts:
                    idx = path_parts.index("reservations")
                    if len(path_parts) > idx + 1 and path_parts[idx + 1].isdigit():
                        reservation_id = int(path_parts[idx + 1])
            except Exception:
                pass

            client_ip = request.client.host if request.client else None
            body_details = None
            if body_bytes:
                try:
                    body_details = json.loads(body_bytes)
                except Exception:
                    body_details = body_bytes.decode(errors="ignore")[:2000]

            # Ohne restaurant_id kein Audit-Log schreiben (DB-Spalte ist not null)
            if restaurant_id is None:
                return response

            details = {
                "method": request.method,
                "path": request.url.path,
                "query": request.url.query,
                "body": body_details,
                "response_status": response.status_code,
            }

            async with async_session() as session:
                await create_audit_log(
                    session,
                    restaurant_id=restaurant_id,
                    user_id=user_id,
                    entity_type="reservation" if "reservations" in path_parts else "request",
                    entity_id=reservation_id,
                    action=request.method.lower(),
                    description=f"{request.method} {request.url.path}",
                    details=details,
                    ip_address=client_ip,
                    use_own_transaction=True,
                )
        except Exception:
            logger.exception(
                "Failed to write audit log (middleware)",
                extra={"method": request.method, "path": request.url.path},
            )

        return response


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Middleware für Request Timeout"""
    
    def __init__(self, app, timeout: int = REQUEST_TIMEOUT):
        super().__init__(app)
        self.timeout = timeout
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            response = await asyncio.wait_for(call_next(request), timeout=self.timeout)
            return response
        except asyncio.TimeoutError:
            logger.error(
                "Request timeout",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "timeout_seconds": self.timeout,
                }
            )
            return Response(
                status_code=504,
                content=json.dumps({"detail": "Request timeout"}),
                media_type="application/json"
            )


class HostValidationMiddleware(BaseHTTPMiddleware):
    """Middleware für Host Validation"""
    
    # Pfade die von externen Services aufgerufen werden (Webhooks)
    WEBHOOK_PATHS = ["/webhook/", "/public/"]
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        host = request.headers.get("host", "").split(":")[0]
        path = request.url.path
        
        # Webhooks und Public APIs von Host-Validierung ausnehmen
        is_webhook = any(wp in path for wp in self.WEBHOOK_PATHS)
        
        if host and host not in ALLOWED_HOSTS and not is_webhook:
            logger.warning(
                "Invalid host",
                extra={"host": host, "allowed": ALLOWED_HOSTS}
            )
            # Nicht blockieren, nur warnen
        
        return await call_next(request)


# ==================== HELPER FUNCTIONS ====================

def log_startup():
    """Loggt Startup-Informationen - kompakt"""
    logger.info(f"🚀 GastroPilot App API gestartet | ENV: {ENV} | Log-Level: {LOG_LEVEL}")


def log_shutdown():
    """Loggt Shutdown-Informationen - kompakt"""
    logger.info("🛑 GastroPilot App API wird heruntergefahren")

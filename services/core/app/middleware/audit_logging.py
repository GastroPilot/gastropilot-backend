from __future__ import annotations

import logging
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.database import get_session_factories
from app.models.audit import AuditLog

logger = logging.getLogger(__name__)


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """Create tenant audit-log entries for successful mutating API requests."""

    MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        method = request.method.upper()
        status = response.status_code
        tenant_id = getattr(request.state, "tenant_id", None)

        if method not in self.MUTATING_METHODS:
            return response
        if status < 200 or status >= 300:
            return response
        if tenant_id is None:
            return response

        entity_type, entity_id = self._derive_entity(request.url.path)
        action = self._map_method_to_action(method)
        user_id = getattr(request.state, "user_id", None)
        ip_address = request.client.host if request.client else None

        try:
            _, admin_factory = get_session_factories()
            async with admin_factory() as session:
                session.add(
                    AuditLog(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        action=action,
                        description=f"{method} {request.url.path}",
                        details={
                            "method": method,
                            "path": request.url.path,
                            "status_code": status,
                        },
                        ip_address=ip_address,
                    )
                )
                await session.commit()
        except Exception as exc:
            logger.warning("Audit middleware konnte keinen Logeintrag schreiben: %s", exc)

        return response

    @staticmethod
    def _map_method_to_action(method: str) -> str:
        if method == "POST":
            return "post"
        if method in {"PATCH", "PUT"}:
            return "patch"
        if method == "DELETE":
            return "delete"
        return method.lower()

    @staticmethod
    def _derive_entity(path: str) -> tuple[str, uuid.UUID | None]:
        parts = [part for part in path.split("/") if part]
        if not parts:
            return "unknown", None

        if len(parts) >= 2 and parts[0] == "api" and parts[1] == "v1":
            parts = parts[2:]
        elif parts and parts[0] == "v1":
            parts = parts[1:]

        if not parts:
            return "unknown", None

        last = parts[-1]
        try:
            entity_id = uuid.UUID(last)
            entity_type = parts[-2] if len(parts) > 1 else "resource"
            return entity_type, entity_id
        except ValueError:
            return last, None

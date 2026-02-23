from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import verify_token
from .schemas import PLATFORM_ROLES, UserRole

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def get_db_user(role: UserRole) -> str:
    """Returns the DB username based on user role."""
    if role in PLATFORM_ROLES:
        return "gastropilot_admin"
    return "gastropilot_app"


async def set_tenant_context(
    session: "AsyncSession",
    tenant_id: uuid.UUID | None,
    role: str,
) -> None:
    """Sets PostgreSQL session variables for RLS."""
    from sqlalchemy import text

    if tenant_id is not None:
        await session.execute(
            text("SELECT set_tenant_context(:tenant_id, :role)"),
            {"tenant_id": str(tenant_id), "role": role},
        )
    else:
        await session.execute(
            text("SELECT set_config('app.current_role', :role, true)"),
            {"role": role},
        )


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Extracts tenant_id from JWT and stores it in request.state.
    The actual DB context is set per-request in the session dependency.
    """

    EXEMPT_PATHS = {
        "/api/v1/health",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/v1/health",
        "/v1/auth/login",
        "/v1/auth/refresh",
        "/docs",
        "/redoc",
        "/openapi.json",
    }

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.EXEMPT_PATHS:
            request.state.tenant_id = None
            request.state.user_id = None
            request.state.role = None
            request.state.is_admin = False
            request.state.is_impersonating = False
            return await call_next(request)

        token = self._extract_token(request)

        if token:
            payload = verify_token(token)
            if payload:
                role_str = payload.get("role")
                try:
                    role = UserRole(role_str) if role_str else None
                except ValueError:
                    role = None

                tenant_id_str = payload.get("tenant_id")
                impersonating_str = payload.get("impersonating_tenant_id")

                tenant_id = None
                if tenant_id_str:
                    try:
                        tenant_id = uuid.UUID(tenant_id_str)
                    except ValueError:
                        pass

                impersonating_tenant_id = None
                if impersonating_str:
                    try:
                        impersonating_tenant_id = uuid.UUID(impersonating_str)
                    except ValueError:
                        pass

                # Determine effective tenant
                effective_tenant = tenant_id
                is_impersonating = False
                if role in PLATFORM_ROLES and impersonating_tenant_id:
                    effective_tenant = impersonating_tenant_id
                    is_impersonating = True

                user_id_str = payload.get("sub") or payload.get("user_id")
                user_id = None
                if user_id_str:
                    try:
                        user_id = uuid.UUID(user_id_str)
                    except ValueError:
                        pass

                request.state.tenant_id = effective_tenant
                request.state.user_id = user_id
                request.state.role = role
                request.state.is_admin = role in PLATFORM_ROLES
                request.state.is_impersonating = is_impersonating
            else:
                request.state.tenant_id = None
                request.state.user_id = None
                request.state.role = None
                request.state.is_admin = False
                request.state.is_impersonating = False
        else:
            request.state.tenant_id = None
            request.state.user_id = None
            request.state.role = None
            request.state.is_admin = False
            request.state.is_impersonating = False

        return await call_next(request)

    def _extract_token(self, request: Request) -> str | None:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        return request.cookies.get("access_token")

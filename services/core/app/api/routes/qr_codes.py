"""QR code generation endpoints for table tokens."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_manager_or_above
from app.models.restaurant import Restaurant, Table
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tables", tags=["qr-codes"])

# 5-Zeichen-Token: Großbuchstaben + Ziffern (ohne verwechselbare: 0/O, 1/I/L)
_TOKEN_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_TOKEN_LENGTH = 5


async def _generate_short_token(db: AsyncSession) -> str:
    """Generate a unique 5-char token, retrying on collision."""
    for _ in range(20):
        token = "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_LENGTH))
        exists = await db.execute(select(Table.id).where(Table.table_token == token))
        if not exists.scalar_one_or_none():
            return token
    raise HTTPException(status_code=500, detail="Could not generate unique token")


def _generate_qr_svg(url: str) -> str:
    """Generate a QR code as SVG string using segno."""
    import io

    import segno

    qr = segno.make(url, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=8, border=2, dark="#000000", light="#ffffff")
    return buf.getvalue().decode("utf-8")


async def _resolve_tenant_context_for_qr(
    request: Request,
    current_user: User,
    db: AsyncSession,
    requested_tenant_id: UUID | None,
) -> UUID:
    effective_tenant_id = getattr(request.state, "tenant_id", None) or current_user.tenant_id
    if effective_tenant_id:
        if requested_tenant_id and requested_tenant_id != effective_tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Requested restaurant_id does not match tenant context",
            )
        return effective_tenant_id

    if current_user.role != "platform_admin":
        raise HTTPException(status_code=403, detail="User has no tenant context")

    if requested_tenant_id:
        restaurant_result = await db.execute(
            select(Restaurant.id).where(Restaurant.id == requested_tenant_id)
        )
        if restaurant_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Restaurant not found")
        return requested_tenant_id

    raise HTTPException(
        status_code=400,
        detail=(
            "Tenant context required (token has no tenant and no restaurant tenant "
            "could be resolved)"
        ),
    )


@router.get("/{table_id}/qr-code")
async def get_table_qr_code(
    request: Request,
    table_id: UUID,
    restaurant_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    """Generate QR code SVG with table token URL."""
    effective_tenant_id = await _resolve_tenant_context_for_qr(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
    )
    result = await db.execute(
        select(Table).where(
            Table.id == table_id,
            Table.tenant_id == effective_tenant_id,
        )
    )
    table = result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    if not table.table_token:
        # Auto-generate short 5-char token
        table.table_token = await _generate_short_token(db)
        table.token_created_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(table)

    # Get restaurant slug for URL
    rest_result = await db.execute(select(Restaurant).where(Restaurant.id == table.tenant_id))
    restaurant = rest_result.scalar_one_or_none()
    slug = restaurant.slug if restaurant else "unknown"

    order_url = f"/order/{slug}/table/{table.table_token}"

    svg = _generate_qr_svg(order_url)

    return {
        "table_id": str(table.id),
        "table_number": table.number,
        "token": table.table_token,
        "order_url": order_url,
        "qr_svg": svg,
    }


@router.post("/{table_id}/regenerate-token")
async def regenerate_table_token(
    request: Request,
    table_id: UUID,
    restaurant_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_manager_or_above),
):
    """Regenerate table token (invalidates old QR codes)."""
    effective_tenant_id = await _resolve_tenant_context_for_qr(
        request=request,
        current_user=current_user,
        db=db,
        requested_tenant_id=restaurant_id,
    )
    result = await db.execute(
        select(Table).where(
            Table.id == table_id,
            Table.tenant_id == effective_tenant_id,
        )
    )
    table = result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    table.table_token = await _generate_short_token(db)
    table.token_created_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(table)

    return {
        "table_id": str(table.id),
        "token": table.table_token,
        "message": "Token regenerated successfully",
    }

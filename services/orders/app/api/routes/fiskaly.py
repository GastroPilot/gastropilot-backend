"""fiskaly KassenSichV TSE management endpoints."""

from __future__ import annotations

import logging
import secrets
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_owner_or_above
from app.models.fiskaly import FiskalyCashPointClosing, FiskalyTransaction, FiskalyTssConfig
from app.services import fiskaly_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fiskaly", tags=["fiskaly"])


def _resolve_tenant_id(request: Request, current_user) -> uuid.UUID:
    """Resolve tenant context for tenant-scoped Fiskaly operations."""
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        return tenant_id

    role = str(getattr(current_user, "role", "") or "")
    if role in {"platform_admin", "platform_support"}:
        raise HTTPException(
            status_code=400,
            detail=(
                "No impersonated tenant in access token. Please select a customer "
                "for impersonation and try again."
            ),
        )

    user_tenant_id = getattr(current_user, "tenant_id", None)
    if user_tenant_id:
        return user_tenant_id

    raise HTTPException(
        status_code=400,
        detail=(
            "No tenant context in access token. Please log in again or "
            "select a tenant before using Fiskaly endpoints."
        ),
    )


class TssSetupRequest(BaseModel):
    admin_pin: str | None = None
    restaurant_name: str = ""
    restaurant_address: str = ""
    restaurant_zip: str = ""
    restaurant_city: str = ""
    restaurant_tax_number: str = ""


class TssSetupResponse(BaseModel):
    tss_id: str
    client_id: str
    client_serial_number: str
    tss_serial_number: str
    state: str


# ---------------------------------------------------------------------------
# TSS management
# ---------------------------------------------------------------------------


@router.post("/tss/setup", response_model=TssSetupResponse)
async def setup_tss(
    body: TssSetupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Create and initialize a TSS for this restaurant (one-click setup)."""
    tenant_id = _resolve_tenant_id(request, current_user)

    if not fiskaly_service._is_configured():
        raise HTTPException(status_code=503, detail="fiskaly not configured")

    # Check if TSS already exists for this tenant
    result = await db.execute(
        select(FiskalyTssConfig).where(FiskalyTssConfig.tenant_id == tenant_id)
    )
    existing = result.scalar_one_or_none()
    if existing and existing.state == "INITIALIZED":
        raise HTTPException(status_code=409, detail="TSS already initialized for this restaurant")

    # Generate admin PIN if not provided (6+ chars required by fiskaly)
    admin_pin = body.admin_pin or secrets.token_hex(4).upper()[:8]
    if len(admin_pin) < 6:
        raise HTTPException(status_code=400, detail="Admin PIN must be at least 6 characters")

    # Step 1: Provision a managed fiskaly organization for this tenant
    org_data = None
    if body.restaurant_name:
        try:
            org_data = await fiskaly_service.provision_tenant_organization(
                restaurant_name=body.restaurant_name,
                restaurant_address=body.restaurant_address,
                restaurant_zip=body.restaurant_zip,
                restaurant_city=body.restaurant_city,
                restaurant_tax_number=body.restaurant_tax_number,
            )
        except Exception as exc:
            logger.error("fiskaly org provisioning failed: %s", exc)
            raise HTTPException(status_code=502, detail=f"Organization setup failed: {exc}")

    # Build a temporary config object for per-tenant credentials
    temp_config = FiskalyTssConfig(
        tenant_id=tenant_id,
        tss_id=uuid.uuid4(),  # placeholder
        client_id=uuid.uuid4(),
        client_serial_number="",
        admin_pin=admin_pin,
        fiskaly_org_id=uuid.UUID(org_data["org_id"]) if org_data else None,
        fiskaly_api_key=org_data["api_key"] if org_data else None,
        fiskaly_api_secret=org_data["api_secret"] if org_data else None,
    )

    # Step 2: Create and initialize TSS with org-specific credentials
    try:
        setup_result = await fiskaly_service.create_and_initialize_tss(temp_config, admin_pin)
    except Exception as exc:
        logger.error("TSS setup failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"TSS setup failed: {exc}")

    # Save or update config
    if existing:
        existing.tss_id = setup_result["tss_id"]
        existing.client_id = setup_result["client_id"]
        existing.client_serial_number = setup_result["client_serial_number"]
        existing.tss_serial_number = setup_result["tss_serial_number"]
        existing.admin_pin = admin_pin
        existing.state = "INITIALIZED"
        if org_data:
            existing.fiskaly_org_id = uuid.UUID(org_data["org_id"])
            existing.fiskaly_api_key = org_data["api_key"]
            existing.fiskaly_api_secret = org_data["api_secret"]
    else:
        config = FiskalyTssConfig(
            tenant_id=tenant_id,
            tss_id=setup_result["tss_id"],
            client_id=setup_result["client_id"],
            client_serial_number=setup_result["client_serial_number"],
            tss_serial_number=setup_result["tss_serial_number"],
            admin_pin=admin_pin,
            state="INITIALIZED",
            fiskaly_org_id=uuid.UUID(org_data["org_id"]) if org_data else None,
            fiskaly_api_key=org_data["api_key"] if org_data else None,
            fiskaly_api_secret=org_data["api_secret"] if org_data else None,
        )
        db.add(config)

    await db.commit()

    return TssSetupResponse(
        tss_id=str(setup_result["tss_id"]),
        client_id=str(setup_result["client_id"]),
        client_serial_number=setup_result["client_serial_number"],
        tss_serial_number=setup_result["tss_serial_number"],
        state="INITIALIZED",
    )


@router.get("/tss/status")
async def get_tss_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Get the TSS configuration status for this restaurant."""
    tenant_id = _resolve_tenant_id(request, current_user)
    result = await db.execute(
        select(FiskalyTssConfig).where(FiskalyTssConfig.tenant_id == tenant_id)
    )
    config = result.scalar_one_or_none()

    if not config:
        return {"configured": False, "state": None}

    return {
        "configured": True,
        "state": config.state,
        "tss_id": str(config.tss_id),
        "client_id": str(config.client_id),
        "client_serial_number": config.client_serial_number,
        "tss_serial_number": config.tss_serial_number,
        "created_at": config.created_at.isoformat() if config.created_at else None,
    }


@router.post("/tss/disable")
async def disable_tss(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Disable the TSS (irreversible!)."""
    tenant_id = _resolve_tenant_id(request, current_user)
    result = await db.execute(
        select(FiskalyTssConfig).where(FiskalyTssConfig.tenant_id == tenant_id)
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(status_code=404, detail="No TSS configured")
    if config.state == "DISABLED":
        raise HTTPException(status_code=409, detail="TSS already disabled")

    try:
        await fiskaly_service.admin_authenticate(config, config.tss_id, config.admin_pin)
        await fiskaly_service.update_tss_state(config, config.tss_id, "DISABLED")
        try:
            await fiskaly_service.admin_logout(config, config.tss_id)
        except Exception:
            logger.warning("TSS admin logout failed after disable (non-critical)")
    except httpx.HTTPStatusError as exc:
        response_text = exc.response.text if exc.response is not None else ""
        is_remote_already_disabled = (
            exc.response is not None
            and exc.response.status_code == 400
            and "E_TSS_DISABLED" in response_text
        )
        if not is_remote_already_disabled:
            logger.error("TSS disable failed: %s", exc)
            raise HTTPException(status_code=502, detail=f"TSS disable failed: {exc}")
        logger.info(
            "TSS already disabled remotely for tenant %s / tss %s",
            tenant_id,
            config.tss_id,
        )
    except Exception as exc:
        logger.error("TSS disable failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"TSS disable failed: {exc}")

    config.state = "DISABLED"
    await db.commit()

    return {"status": "disabled", "tss_id": str(config.tss_id)}


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


@router.get("/transactions")
async def list_transactions(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """List signed TSE transactions for this restaurant."""
    tenant_id = _resolve_tenant_id(request, current_user)
    result = await db.execute(
        select(FiskalyTransaction)
        .where(FiskalyTransaction.tenant_id == tenant_id)
        .order_by(FiskalyTransaction.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    transactions = result.scalars().all()

    return [
        {
            "id": str(tx.id),
            "order_id": str(tx.order_id),
            "tx_number": tx.tx_number,
            "tx_state": tx.tx_state,
            "receipt_type": tx.receipt_type,
            "qr_code_data": tx.qr_code_data,
            "signature_value": tx.signature_value,
            "tss_serial_number": tx.tss_serial_number,
            "error": tx.error,
            "receipt_id": tx.receipt_id,
            "receipt_public_url": tx.receipt_public_url,
            "receipt_pdf_url": tx.receipt_pdf_url,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
        }
        for tx in transactions
    ]


@router.get("/transactions/{order_id}")
async def get_transaction_for_order(
    order_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Get the TSE transaction data for a specific order."""
    tenant_id = _resolve_tenant_id(request, current_user)
    result = await db.execute(
        select(FiskalyTransaction)
        .where(
            FiskalyTransaction.tenant_id == tenant_id,
            FiskalyTransaction.order_id == order_id,
        )
        .order_by(FiskalyTransaction.created_at.desc())
    )
    tx = result.scalars().first()

    if not tx:
        raise HTTPException(status_code=404, detail="No TSE transaction for this order")

    return {
        "id": str(tx.id),
        "order_id": str(tx.order_id),
        "tx_id": str(tx.tx_id),
        "tx_number": tx.tx_number,
        "tx_state": tx.tx_state,
        "receipt_type": tx.receipt_type,
        "time_start": tx.time_start,
        "time_end": tx.time_end,
        "signature_value": tx.signature_value,
        "signature_algorithm": tx.signature_algorithm,
        "signature_counter": tx.signature_counter,
        "qr_code_data": tx.qr_code_data,
        "tss_serial_number": tx.tss_serial_number,
        "client_serial_number": tx.client_serial_number,
        "error": tx.error,
        "receipt_id": tx.receipt_id,
        "receipt_public_url": tx.receipt_public_url,
        "receipt_pdf_url": tx.receipt_pdf_url,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
    }


@router.post("/transactions/{order_id}/retry")
async def retry_transaction(
    order_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Retry signing for a failed TSE transaction."""
    from app.models.order import Order

    tenant_id = _resolve_tenant_id(request, current_user)

    # Load order
    order_result = await db.execute(
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
    )
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Check if there's already a successful transaction
    existing_result = await db.execute(
        select(FiskalyTransaction).where(
            FiskalyTransaction.order_id == order_id,
            FiskalyTransaction.tx_state == "FINISHED",
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Order already has a signed transaction")

    payment_type = fiskaly_service.resolve_payment_type(order.payment_method)
    tx = await fiskaly_service.sign_order_receipt(db, order, payment_type=payment_type)
    if not tx:
        raise HTTPException(status_code=503, detail="TSE signing not available")

    await db.commit()

    if tx.error:
        raise HTTPException(status_code=502, detail=f"Signing failed: {tx.error}")

    return {
        "status": "signed",
        "tx_number": tx.tx_number,
        "qr_code_data": tx.qr_code_data,
    }


# ---------------------------------------------------------------------------
# Exports (Finanzamt / DSFinV-K)
# ---------------------------------------------------------------------------


class ExportTriggerRequest(BaseModel):
    start_date: str | None = None  # ISO date string e.g. "2026-01-01"
    end_date: str | None = None


@router.post("/exports/trigger")
async def trigger_export(
    body: ExportTriggerRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Trigger a TSS export for the tax authorities."""
    from datetime import UTC
    from datetime import datetime as dt

    tenant_id = _resolve_tenant_id(request, current_user)

    result = await db.execute(
        select(FiskalyTssConfig).where(
            FiskalyTssConfig.tenant_id == tenant_id,
            FiskalyTssConfig.state == "INITIALIZED",
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="No initialized TSS")

    # Convert ISO dates to unix timestamps
    start_ts = None
    end_ts = None
    if body.start_date:
        start_ts = int(dt.fromisoformat(body.start_date).replace(tzinfo=UTC).timestamp())
    if body.end_date:
        end_ts = int(
            dt.fromisoformat(body.end_date)
            .replace(hour=23, minute=59, second=59, tzinfo=UTC)
            .timestamp()
        )

    export_id = uuid.uuid4()
    try:
        resp = await fiskaly_service.trigger_export(
            config, config.tss_id, export_id, start_date=start_ts, end_date=end_ts
        )
    except Exception as exc:
        logger.error("Export trigger failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Export trigger failed: {exc}")

    return {
        "export_id": str(export_id),
        "tss_id": str(config.tss_id),
        "state": resp.get("state", "PENDING"),
        "time_request": resp.get("time_request"),
    }


@router.get("/exports/{export_id}/status")
async def get_export_status(
    export_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Poll the status of an export."""
    tenant_id = _resolve_tenant_id(request, current_user)

    result = await db.execute(
        select(FiskalyTssConfig).where(FiskalyTssConfig.tenant_id == tenant_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="No TSS configured")

    try:
        resp = await fiskaly_service.get_export(config, config.tss_id, export_id)
    except Exception as exc:
        logger.error("Export status failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    return {
        "export_id": str(export_id),
        "state": resp.get("state"),
        "time_start": resp.get("time_start"),
        "time_end": resp.get("time_end"),
        "time_expiration": resp.get("time_expiration"),
        "estimated_time_of_completion": resp.get("estimated_time_of_completion"),
    }


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Download the TAR file of a completed export."""
    from fastapi.responses import Response

    tenant_id = _resolve_tenant_id(request, current_user)

    result = await db.execute(
        select(FiskalyTssConfig).where(FiskalyTssConfig.tenant_id == tenant_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="No TSS configured")

    # Verify export is completed
    try:
        status = await fiskaly_service.get_export(config, config.tss_id, export_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if status.get("state") != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"Export not ready (state: {status.get('state')})",
        )

    try:
        tar_data = await fiskaly_service.get_export_file(config, config.tss_id, export_id)
    except Exception as exc:
        logger.error("Export download failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    return Response(
        content=tar_data,
        media_type="application/x-tar",
        headers={"Content-Disposition": f'attachment; filename="tse-export-{export_id}.tar"'},
    )


@router.get("/exports")
async def list_exports(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """List all exports for this restaurant's TSS."""
    tenant_id = _resolve_tenant_id(request, current_user)

    result = await db.execute(
        select(FiskalyTssConfig).where(FiskalyTssConfig.tenant_id == tenant_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="No TSS configured")

    try:
        resp = await fiskaly_service.list_exports(config, config.tss_id)
    except Exception as exc:
        logger.error("List exports failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    exports = resp if isinstance(resp, list) else resp.get("data", [])
    return [
        {
            "export_id": str(e.get("_id", "")),
            "state": e.get("state"),
            "time_request": e.get("time_request"),
            "time_end": e.get("time_end"),
            "time_expiration": e.get("time_expiration"),
        }
        for e in exports
    ]


# ---------------------------------------------------------------------------
# eReceipt
# ---------------------------------------------------------------------------


class ReceiptCreateRequest(BaseModel):
    order_id: uuid.UUID
    restaurant_name: str
    restaurant_address: str = ""
    restaurant_tax_number: str = ""


@router.post("/receipts/create")
async def create_receipt_for_order(
    body: ReceiptCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Create a fiskaly eReceipt for a signed order."""
    from app.models.order import Order, OrderItem

    tenant_id = _resolve_tenant_id(request, current_user)

    # Load order
    order_result = await db.execute(
        select(Order).where(Order.id == body.order_id, Order.tenant_id == tenant_id)
    )
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Load TSE transaction
    tx_result = await db.execute(
        select(FiskalyTransaction).where(
            FiskalyTransaction.order_id == body.order_id,
            FiskalyTransaction.tx_state == "FINISHED",
        )
    )
    tse_tx = tx_result.scalars().first()
    if not tse_tx:
        raise HTTPException(status_code=404, detail="No signed TSE transaction for this order")

    if tse_tx.receipt_id:
        return {
            "receipt_id": tse_tx.receipt_id,
            "public_url": tse_tx.receipt_public_url,
            "pdf_url": tse_tx.receipt_pdf_url,
            "status": "already_exists",
        }

    # Load TSS config for per-tenant credentials
    tss_result = await db.execute(
        select(FiskalyTssConfig).where(FiskalyTssConfig.tenant_id == tenant_id)
    )
    tss_config = tss_result.scalar_one_or_none()
    if not tss_config:
        raise HTTPException(status_code=404, detail="No TSS configured")

    # Load order items
    items_result = await db.execute(select(OrderItem).where(OrderItem.order_id == body.order_id))
    items = list(items_result.scalars().all())

    payment_type = fiskaly_service.resolve_payment_type(order.payment_method)

    try:
        resp = await fiskaly_service.create_receipt(
            config=tss_config,
            order=order,
            items=items,
            tse_data=tse_tx,
            restaurant_name=body.restaurant_name,
            restaurant_address=body.restaurant_address,
            restaurant_tax_number=body.restaurant_tax_number,
            payment_type=payment_type,
        )
    except Exception as exc:
        logger.error("Receipt creation failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Receipt creation failed: {exc}")

    # Store receipt data
    tse_tx.receipt_id = resp.get("_id", "")
    tse_tx.receipt_public_url = resp.get("public_link", {}).get("href", "")
    tse_tx.receipt_pdf_url = resp.get("assets", {}).get("pdf_link", "")
    await db.commit()

    return {
        "receipt_id": tse_tx.receipt_id,
        "public_url": tse_tx.receipt_public_url,
        "pdf_url": tse_tx.receipt_pdf_url,
        "status": "created",
    }


# ---------------------------------------------------------------------------
# Tagesabschluss (DSFinV-K Cash Point Closing)
# ---------------------------------------------------------------------------


class DailyClosingRequest(BaseModel):
    business_date: str  # YYYY-MM-DD


class DailyClosingResponse(BaseModel):
    closing_id: str
    business_date: str
    state: str
    total_amount: float | None = None
    total_cash: float | None = None
    total_non_cash: float | None = None
    transaction_count: int | None = None
    error: str | None = None
    created_at: str | None = None


@router.post("/daily-closing", response_model=DailyClosingResponse)
async def create_daily_closing(
    body: DailyClosingRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Perform a daily cash point closing (Tagesabschluss) for DSFinV-K."""
    import re

    tenant_id = _resolve_tenant_id(request, current_user)

    if not fiskaly_service._is_configured():
        raise HTTPException(status_code=503, detail="fiskaly not configured")

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", body.business_date):
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    try:
        record = await fiskaly_service.perform_daily_closing(db, tenant_id, body.business_date)
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.error("Daily closing failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Tagesabschluss fehlgeschlagen: {exc}")

    return DailyClosingResponse(
        closing_id=str(record.closing_id),
        business_date=record.business_date,
        state=record.state,
        total_amount=record.total_amount,
        total_cash=record.total_cash,
        total_non_cash=record.total_non_cash,
        transaction_count=record.transaction_count,
        error=record.error,
        created_at=record.created_at.isoformat() if record.created_at else None,
    )


@router.get("/daily-closings")
async def list_daily_closings(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """List all daily closings for this restaurant."""
    tenant_id = _resolve_tenant_id(request, current_user)

    result = await db.execute(
        select(FiskalyCashPointClosing)
        .where(FiskalyCashPointClosing.tenant_id == tenant_id)
        .order_by(FiskalyCashPointClosing.business_date.desc())
        .limit(limit)
        .offset(offset)
    )
    closings = list(result.scalars().all())

    # Refresh state for non-final closings from DSFinV-K
    pending = [c for c in closings if c.state in ("PENDING", "WORKING")]
    if pending:
        tss_result = await db.execute(
            select(FiskalyTssConfig).where(FiskalyTssConfig.tenant_id == tenant_id)
        )
        tss_config = tss_result.scalar_one_or_none()
        if tss_config:
            for c in pending:
                try:
                    remote = await fiskaly_service.dsfinvk_get_cash_point_closing(
                        tss_config, c.closing_id
                    )
                    remote_state = remote.get("state")
                    if remote_state and remote_state != c.state:
                        c.state = remote_state
                except Exception:
                    pass
            await db.commit()

    return [
        {
            "closing_id": str(c.closing_id),
            "business_date": c.business_date,
            "state": c.state,
            "total_amount": c.total_amount,
            "total_cash": c.total_cash,
            "total_non_cash": c.total_non_cash,
            "transaction_count": c.transaction_count,
            "error": c.error,
            "is_automatic": c.is_automatic,
            "dsfinvk_export_id": str(c.dsfinvk_export_id) if c.dsfinvk_export_id else None,
            "dsfinvk_export_state": c.dsfinvk_export_state,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in closings
    ]


@router.get("/daily-closings/{closing_id}")
async def get_daily_closing(
    closing_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Get a specific daily closing with details."""
    tenant_id = _resolve_tenant_id(request, current_user)

    result = await db.execute(
        select(FiskalyCashPointClosing).where(
            FiskalyCashPointClosing.tenant_id == tenant_id,
            FiskalyCashPointClosing.closing_id == closing_id,
        )
    )
    closing = result.scalar_one_or_none()
    if not closing:
        raise HTTPException(status_code=404, detail="Tagesabschluss nicht gefunden")

    # Also fetch status from DSFinV-K if not in final state
    remote_state = None
    if closing.state not in ("ERROR", "DELETED"):
        try:
            tss_result = await db.execute(
                select(FiskalyTssConfig).where(FiskalyTssConfig.tenant_id == tenant_id)
            )
            tss_config = tss_result.scalar_one_or_none()
            if tss_config:
                remote = await fiskaly_service.dsfinvk_get_cash_point_closing(
                    tss_config, closing_id
                )
                remote_state = remote.get("state")
                if remote_state and remote_state != closing.state:
                    closing.state = remote_state
                    await db.commit()
        except Exception as exc:
            logger.warning("DSFinV-K closing status fetch failed: %s", exc)

    return {
        "closing_id": str(closing.closing_id),
        "business_date": closing.business_date,
        "state": closing.state,
        "total_amount": closing.total_amount,
        "total_cash": closing.total_cash,
        "total_non_cash": closing.total_non_cash,
        "transaction_count": closing.transaction_count,
        "error": closing.error,
        "is_automatic": closing.is_automatic,
        "dsfinvk_export_id": str(closing.dsfinvk_export_id) if closing.dsfinvk_export_id else None,
        "dsfinvk_export_state": closing.dsfinvk_export_state,
        "created_at": closing.created_at.isoformat() if closing.created_at else None,
        "updated_at": closing.updated_at.isoformat() if closing.updated_at else None,
    }


@router.delete("/daily-closings/{closing_id}")
async def delete_daily_closing(
    closing_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Delete a daily closing (also removes from DSFinV-K)."""
    tenant_id = _resolve_tenant_id(request, current_user)

    result = await db.execute(
        select(FiskalyCashPointClosing).where(
            FiskalyCashPointClosing.tenant_id == tenant_id,
            FiskalyCashPointClosing.closing_id == closing_id,
        )
    )
    closing = result.scalar_one_or_none()
    if not closing:
        raise HTTPException(status_code=404, detail="Tagesabschluss nicht gefunden")

    # Delete from DSFinV-K
    try:
        tss_result = await db.execute(
            select(FiskalyTssConfig).where(FiskalyTssConfig.tenant_id == tenant_id)
        )
        tss_config = tss_result.scalar_one_or_none()
        if tss_config:
            await fiskaly_service.dsfinvk_delete_cash_point_closing(tss_config, closing_id)
    except Exception as exc:
        logger.warning("DSFinV-K remote delete failed (continuing locally): %s", exc)

    closing.state = "DELETED"
    await db.commit()

    return {"status": "deleted", "closing_id": str(closing_id)}


# ---------------------------------------------------------------------------
# DSFinV-K Export (separate from TSE export)
# ---------------------------------------------------------------------------


class DsfinvkExportRequest(BaseModel):
    business_date_start: str | None = None  # YYYY-MM-DD
    business_date_end: str | None = None  # YYYY-MM-DD
    closing_id: str | None = None  # UUID for single closing export
    format: str = "ZIP"  # ZIP or TAR


@router.post("/dsfinvk-exports/trigger")
async def trigger_dsfinvk_export(
    body: DsfinvkExportRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Trigger a DSFinV-K export."""
    tenant_id = _resolve_tenant_id(request, current_user)

    tss_result = await db.execute(
        select(FiskalyTssConfig).where(
            FiskalyTssConfig.tenant_id == tenant_id,
            FiskalyTssConfig.state == "INITIALIZED",
        )
    )
    tss_config = tss_result.scalar_one_or_none()
    if not tss_config:
        raise HTTPException(status_code=404, detail="Keine initialisierte TSS")

    export_id = uuid.uuid4()
    export_body: dict = {}

    if body.closing_id:
        export_body["cash_point_closing_id"] = body.closing_id
        # Look up the closing's business_date to satisfy the oneOf requirement
        closing_result = await db.execute(
            select(FiskalyCashPointClosing).where(
                FiskalyCashPointClosing.tenant_id == tenant_id,
                FiskalyCashPointClosing.closing_id == uuid.UUID(body.closing_id),
            )
        )
        closing_record = closing_result.scalar_one_or_none()
        if closing_record:
            export_body["business_date_start"] = closing_record.business_date
            export_body["business_date_end"] = closing_record.business_date
        else:
            # Fallback: use today
            from datetime import date
            today = date.today().isoformat()
            export_body["business_date_start"] = today
            export_body["business_date_end"] = today
    elif body.business_date_start and body.business_date_end:
        export_body["business_date_start"] = body.business_date_start
        export_body["business_date_end"] = body.business_date_end
    else:
        raise HTTPException(
            status_code=400,
            detail="Entweder closing_id oder business_date_start + business_date_end angeben",
        )

    try:
        resp = await fiskaly_service.dsfinvk_trigger_export(tss_config, export_id, export_body)
    except Exception as exc:
        logger.error("DSFinV-K export trigger failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Export-Auslösung fehlgeschlagen: {exc}")

    # Update closing record if single-closing export
    if body.closing_id:
        closing_result = await db.execute(
            select(FiskalyCashPointClosing).where(
                FiskalyCashPointClosing.tenant_id == tenant_id,
                FiskalyCashPointClosing.closing_id == uuid.UUID(body.closing_id),
            )
        )
        closing = closing_result.scalar_one_or_none()
        if closing:
            closing.dsfinvk_export_id = export_id
            closing.dsfinvk_export_state = resp.get("state", "PENDING")
            await db.commit()

    return {
        "export_id": str(export_id),
        "state": resp.get("state", "PENDING"),
    }


@router.get("/dsfinvk-exports/{export_id}/status")
async def get_dsfinvk_export_status(
    export_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Get status of a DSFinV-K export."""
    tenant_id = _resolve_tenant_id(request, current_user)

    tss_result = await db.execute(
        select(FiskalyTssConfig).where(FiskalyTssConfig.tenant_id == tenant_id)
    )
    tss_config = tss_result.scalar_one_or_none()
    if not tss_config:
        raise HTTPException(status_code=404, detail="Keine TSS konfiguriert")

    try:
        resp = await fiskaly_service.dsfinvk_get_export(tss_config, export_id)
    except Exception as exc:
        logger.error("DSFinV-K export status failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    # Update closing record if export state changed
    state = resp.get("state")
    if state in ("COMPLETED", "ERROR", "CANCELLED"):
        closing_result = await db.execute(
            select(FiskalyCashPointClosing).where(
                FiskalyCashPointClosing.tenant_id == tenant_id,
                FiskalyCashPointClosing.dsfinvk_export_id == export_id,
            )
        )
        closing = closing_result.scalar_one_or_none()
        if closing and closing.dsfinvk_export_state != state:
            closing.dsfinvk_export_state = state
            await db.commit()

    return {
        "export_id": str(export_id),
        "state": state,
        "time_creation": resp.get("time_creation"),
        "time_update": resp.get("time_update"),
    }


@router.get("/dsfinvk-exports/{export_id}/download")
async def download_dsfinvk_export(
    export_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Download a completed DSFinV-K export file."""
    from fastapi.responses import Response

    tenant_id = _resolve_tenant_id(request, current_user)

    tss_result = await db.execute(
        select(FiskalyTssConfig).where(FiskalyTssConfig.tenant_id == tenant_id)
    )
    tss_config = tss_result.scalar_one_or_none()
    if not tss_config:
        raise HTTPException(status_code=404, detail="Keine TSS konfiguriert")

    # Verify export is completed
    try:
        status = await fiskaly_service.dsfinvk_get_export(tss_config, export_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if status.get("state") != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"Export nicht bereit (Status: {status.get('state')})",
        )

    try:
        file_data = await fiskaly_service.dsfinvk_download_export(tss_config, export_id)
    except Exception as exc:
        logger.error("DSFinV-K export download failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    return Response(
        content=file_data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="dsfinvk-export-{export_id}.zip"'
        },
    )


@router.get("/dsfinvk-exports")
async def list_dsfinvk_exports(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """List all DSFinV-K exports."""
    tenant_id = _resolve_tenant_id(request, current_user)

    tss_result = await db.execute(
        select(FiskalyTssConfig).where(FiskalyTssConfig.tenant_id == tenant_id)
    )
    tss_config = tss_result.scalar_one_or_none()
    if not tss_config:
        raise HTTPException(status_code=404, detail="Keine TSS konfiguriert")

    try:
        resp = await fiskaly_service.dsfinvk_list_exports(tss_config)
    except Exception as exc:
        logger.error("DSFinV-K list exports failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    exports = resp.get("data", []) if isinstance(resp, dict) else resp
    return [
        {
            "export_id": str(e.get("_id", e.get("export_id", ""))),
            "state": e.get("state"),
            "time_creation": e.get("time_creation"),
            "time_update": e.get("time_update"),
        }
        for e in exports
    ]


# ---------------------------------------------------------------------------
# Tagesabschluss PDF
# ---------------------------------------------------------------------------


@router.get("/daily-closings/{closing_id}/pdf")
async def download_daily_closing_pdf(
    closing_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Generate a PDF summary of a daily closing (Tagesabschluss)."""
    import io
    from datetime import UTC as _UTC
    from datetime import datetime as dt

    from fastapi.responses import StreamingResponse

    tenant_id = _resolve_tenant_id(request, current_user)

    # Load closing
    result = await db.execute(
        select(FiskalyCashPointClosing).where(
            FiskalyCashPointClosing.tenant_id == tenant_id,
            FiskalyCashPointClosing.closing_id == closing_id,
        )
    )
    closing = result.scalar_one_or_none()
    if not closing:
        raise HTTPException(status_code=404, detail="Tagesabschluss nicht gefunden")

    # Load orders for this day
    from app.models.order import Order, OrderItem

    day_start = dt.fromisoformat(f"{closing.business_date}T00:00:00").replace(tzinfo=_UTC)
    day_end = dt.fromisoformat(f"{closing.business_date}T23:59:59").replace(tzinfo=_UTC)

    orders_result = await db.execute(
        select(Order).where(
            Order.tenant_id == tenant_id,
            Order.payment_status == "paid",
            Order.opened_at >= day_start,
            Order.opened_at <= day_end,
        ).order_by(Order.opened_at)
    )
    orders = list(orders_result.scalars().all())

    order_ids = [o.id for o in orders]

    # Load items
    items_result = await db.execute(
        select(OrderItem).where(OrderItem.order_id.in_(order_ids))
    )
    all_items = list(items_result.scalars().all())
    items_by_order: dict[uuid.UUID, list] = {}
    for item in all_items:
        items_by_order.setdefault(item.order_id, []).append(item)

    # Load restaurant name
    restaurant_name = "Restaurant"
    try:
        from app.models.order import Order as _O  # noqa: F811

        if orders:
            restaurant_name = getattr(orders[0], "restaurant_name", None) or "Restaurant"
    except Exception:
        pass

    # Build PDF
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            HRFlowable,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
        )
        from reportlab.platypus import Table as RLTable
        from reportlab.platypus import (
            TableStyle,
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="ReportLab nicht installiert")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    accent = colors.HexColor("#1a1a2e")
    light_bg = colors.HexColor("#f8f9fa")

    style_small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=7, leading=9)
    style_label = ParagraphStyle(
        "Label", parent=styles["Normal"], fontSize=8, textColor=colors.grey
    )

    story: list = []

    # ── Header ──
    story.append(Paragraph("TAGESABSCHLUSS", styles["Title"]))
    story.append(Spacer(1, 2 * mm))
    story.append(
        Paragraph(
            f"Datum: <b>{closing.business_date}</b> &nbsp;|&nbsp; "
            f"Abschluss-Nr: <b>{closing.closing_id}</b>",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 1 * mm))
    story.append(
        Paragraph(
            f"Status: <b>{closing.state}</b> &nbsp;|&nbsp; "
            f"Erstellt: {closing.created_at.strftime('%d.%m.%Y %H:%M') if closing.created_at else '-'}",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=accent))
    story.append(Spacer(1, 6 * mm))

    # ── Summary cards ──
    total_amount = closing.total_amount or 0
    total_cash = closing.total_cash or 0
    total_non_cash = closing.total_non_cash or 0
    tx_count = closing.transaction_count or len(orders)

    summary_data = [
        ["Gesamtumsatz", "Bar", "Unbar", "Transaktionen"],
        [
            f"{total_amount:.2f} EUR",
            f"{total_cash:.2f} EUR",
            f"{total_non_cash:.2f} EUR",
            str(tx_count),
        ],
    ]
    summary_table = RLTable(summary_data, colWidths=[120, 120, 120, 100])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), accent),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("FONTSIZE", (0, 1), (-1, 1), 11),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("TOPPADDING", (0, 1), (-1, 1), 10),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
                ("BACKGROUND", (0, 1), (-1, 1), light_bg),
                ("BOX", (0, 0), (-1, -1), 0.5, accent),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 6 * mm))

    # ── Tax breakdown ──
    tax_buckets: dict[float, dict[str, float]] = {}
    for order in orders:
        for item in items_by_order.get(order.id, []):
            if item.status == "canceled":
                continue
            rate = item.tax_rate
            gross = float(item.total_price)
            net = gross / (1 + rate) if rate > 0 else gross
            vat = gross - net
            if rate not in tax_buckets:
                tax_buckets[rate] = {"gross": 0, "net": 0, "vat": 0}
            tax_buckets[rate]["gross"] += gross
            tax_buckets[rate]["net"] += net
            tax_buckets[rate]["vat"] += vat

    if tax_buckets:
        story.append(Paragraph("Steueraufschlüsselung", styles["Heading3"]))
        story.append(Spacer(1, 2 * mm))

        tax_data = [["MwSt-Satz", "Brutto", "Netto", "MwSt"]]
        total_vat = 0.0
        for rate in sorted(tax_buckets.keys(), reverse=True):
            b = tax_buckets[rate]
            total_vat += b["vat"]
            pct = f"{rate * 100:.0f}%" if rate > 0 else "0%"
            tax_data.append([
                pct,
                f"{b['gross']:.2f} EUR",
                f"{b['net']:.2f} EUR",
                f"{b['vat']:.2f} EUR",
            ])
        tax_data.append([
            "Gesamt",
            f"{sum(b['gross'] for b in tax_buckets.values()):.2f} EUR",
            f"{sum(b['net'] for b in tax_buckets.values()):.2f} EUR",
            f"{total_vat:.2f} EUR",
        ])

        tax_table = RLTable(tax_data, colWidths=[100, 120, 120, 120])
        tax_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9ecef")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dee2e6")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(tax_table)
        story.append(Spacer(1, 6 * mm))

    # ── Payment methods breakdown ──
    payment_methods: dict[str, float] = {}
    for order in orders:
        method = order.payment_method or "Sonstige"
        payment_methods[method] = payment_methods.get(method, 0) + float(order.total or 0)

    if payment_methods:
        story.append(Paragraph("Zahlungsarten", styles["Heading3"]))
        story.append(Spacer(1, 2 * mm))

        pm_data = [["Zahlungsart", "Betrag", "Anteil"]]
        for method, amount in sorted(payment_methods.items(), key=lambda x: -x[1]):
            pct = (amount / total_amount * 100) if total_amount > 0 else 0
            pm_data.append([method, f"{amount:.2f} EUR", f"{pct:.1f}%"])

        pm_table = RLTable(pm_data, colWidths=[200, 130, 130])
        pm_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9ecef")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dee2e6")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(pm_table)
        story.append(Spacer(1, 6 * mm))

    # ── Orders list ──
    story.append(Paragraph("Bestellungen", styles["Heading3"]))
    story.append(Spacer(1, 2 * mm))

    order_data = [["Nr.", "Zeit", "Zahlungsart", "Betrag"]]
    for order in orders:
        t = order.opened_at.strftime("%H:%M") if order.opened_at else "-"
        nr = order.order_number or str(order.id)[:8]
        method = order.payment_method or "-"
        order_data.append([nr, t, method, f"{float(order.total or 0):.2f} EUR"])

    if len(order_data) > 1:
        order_table = RLTable(order_data, colWidths=[80, 80, 160, 140])
        order_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9ecef")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ALIGN", (3, 0), (3, -1), "RIGHT"),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dee2e6")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, light_bg]),
                ]
            )
        )
        story.append(order_table)
    else:
        story.append(Paragraph("Keine Bestellungen.", styles["Normal"]))

    # ── Footer ──
    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 2 * mm))
    story.append(
        Paragraph(
            f"Generiert am {dt.now(tz=_UTC).strftime('%d.%m.%Y %H:%M:%S')} UTC "
            f"&bull; GastroPilot Tagesabschluss",
            style_small,
        )
    )

    doc.build(story)
    buffer.seek(0)

    filename = f"tagesabschluss_{closing.business_date}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Dashboard warnings
# ---------------------------------------------------------------------------


@router.get("/daily-closing-warnings")
async def get_daily_closing_warnings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_owner_or_above),
):
    """Return warnings about automatic daily closings for the dashboard."""
    from datetime import date, timedelta

    tenant_id = _resolve_tenant_id(request, current_user)

    yesterday = (date.today() - timedelta(days=1)).isoformat()

    result = await db.execute(
        select(FiskalyCashPointClosing).where(
            FiskalyCashPointClosing.tenant_id == tenant_id,
            FiskalyCashPointClosing.business_date == yesterday,
            FiskalyCashPointClosing.is_automatic.is_(True),
            FiskalyCashPointClosing.state.notin_(["DELETED"]),
        )
    )
    auto_closing = result.scalar_one_or_none()

    warnings = []
    if auto_closing:
        warnings.append({
            "type": "auto_daily_closing",
            "severity": "warning",
            "business_date": auto_closing.business_date,
            "closing_id": str(auto_closing.closing_id),
            "state": auto_closing.state,
            "total_amount": auto_closing.total_amount,
            "message": (
                f"Der Tagesabschluss für den {auto_closing.business_date} wurde "
                f"automatisch um 23:59 Uhr durchgeführt. Bitte prüfen Sie die Daten."
            ),
        })

    return {"warnings": warnings}

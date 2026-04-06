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
from app.models.fiskaly import FiskalyTransaction, FiskalyTssConfig
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
    from datetime import UTC, datetime as dt

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

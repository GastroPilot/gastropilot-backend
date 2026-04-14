"""fiskaly SIGN DE API v2 + Management API + eReceipt API client."""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.fiskaly import FiskalyCashPointClosing, FiskalyTransaction, FiskalyTssConfig
from app.models.order import Order, OrderItem

logger = logging.getLogger(__name__)

_TOKEN_BUFFER_SECONDS = 30

# Per-credential token cache: key=api_key, value=(token, expires_at, refresh_token)
_token_cache: dict[str, tuple[str, float, str | None]] = {}


def _is_configured() -> bool:
    return bool(settings.FISKALY_API_KEY and settings.FISKALY_API_SECRET)


# ---------------------------------------------------------------------------
# Generic token management (per-credential)
# ---------------------------------------------------------------------------


async def _authenticate_at(
    base_url: str, api_key: str, api_secret: str
) -> tuple[str, float, str | None]:
    """Authenticate at a fiskaly API and return (token, expires_at, refresh_token)."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        resp = await client.post(
            f"{base_url}/auth",
            json={"api_key": api_key, "api_secret": api_secret},
        )
        resp.raise_for_status()
        data = resp.json()
    token = data["access_token"]
    expires_at = time.time() + data.get("access_token_expires_in", 600)
    refresh = data.get("refresh_token")
    _token_cache[api_key] = (token, expires_at, refresh)
    return token, expires_at, refresh


async def _ensure_token_for(base_url: str, api_key: str, api_secret: str) -> str:
    """Get a valid token for the given credentials, refreshing if needed."""
    cached = _token_cache.get(api_key)
    if cached:
        token, expires_at, refresh = cached
        if time.time() < expires_at - _TOKEN_BUFFER_SECONDS:
            return token
        # Try refresh
        if refresh:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                    resp = await client.post(f"{base_url}/auth", json={"refresh_token": refresh})
                    resp.raise_for_status()
                    data = resp.json()
                new_token = data["access_token"]
                new_expires = time.time() + data.get("access_token_expires_in", 600)
                new_refresh = data.get("refresh_token", refresh)
                _token_cache[api_key] = (new_token, new_expires, new_refresh)
                return new_token
            except httpx.HTTPError:
                logger.warning("Token refresh failed for %s..., re-authenticating", api_key[:12])

    token, _, _ = await _authenticate_at(base_url, api_key, api_secret)
    return token


async def _api_request(
    base_url: str,
    api_key: str,
    api_secret: str,
    method: str,
    path: str,
    json_body: dict | None = None,
) -> dict:
    """Send an authenticated request to any fiskaly API."""
    token = await _ensure_token_for(base_url, api_key, api_secret)
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}{path}"

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.request(method, url, json=json_body, headers=headers)

        if resp.status_code == 401:
            token, _, _ = await _authenticate_at(base_url, api_key, api_secret)
            headers["Authorization"] = f"Bearer {token}"
            resp = await client.request(method, url, json=json_body, headers=headers)

        if resp.status_code >= 400:
            logger.error("fiskaly %s %s → %s: %s", method, path, resp.status_code, resp.text)
            resp.raise_for_status()
        return resp.json()


# Convenience: request with master credentials against SIGN DE API
async def _request(method: str, path: str, json_body: dict | None = None) -> dict:
    return await _api_request(
        settings.FISKALY_BASE_URL,
        settings.FISKALY_API_KEY,
        settings.FISKALY_API_SECRET,
        method,
        path,
        json_body,
    )


# Request with per-tenant credentials
async def _tenant_request(
    config: FiskalyTssConfig, method: str, path: str, json_body: dict | None = None
) -> dict:
    api_key = config.fiskaly_api_key or settings.FISKALY_API_KEY
    api_secret = config.fiskaly_api_secret or settings.FISKALY_API_SECRET
    return await _api_request(
        settings.FISKALY_BASE_URL, api_key, api_secret, method, path, json_body
    )


# ---------------------------------------------------------------------------
# Management API (https://dashboard.fiskaly.com/api/v0)
# ---------------------------------------------------------------------------


async def _mgmt_request(method: str, path: str, json_body: dict | None = None) -> dict:
    """Request against the fiskaly Management API with master credentials."""
    return await _api_request(
        settings.FISKALY_MANAGEMENT_URL,
        settings.FISKALY_API_KEY,
        settings.FISKALY_API_SECRET,
        method,
        path,
        json_body,
    )


async def get_master_org_id() -> str:
    """Get the organization_id by authenticating and reading the response claims."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        resp = await client.post(
            f"{settings.FISKALY_MANAGEMENT_URL}/auth",
            json={
                "api_key": settings.FISKALY_API_KEY,
                "api_secret": settings.FISKALY_API_SECRET,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    claims = data.get("access_token_claims", {})
    org_id = claims.get("organization_id", "")
    logger.info("Master organization ID: %s", org_id)
    return org_id


async def create_managed_organization(
    name: str,
    address_line1: str,
    zip_code: str,
    town: str,
    country_code: str = "DEU",
    tax_number: str = "",
    managed_by_org_id: str | None = None,
) -> dict:
    """Create a managed organization under the master org."""
    if not managed_by_org_id:
        managed_by_org_id = await get_master_org_id()

    # Ensure managed_by_org_id is valid UUID format
    try:
        managed_by_org_id = str(uuid.UUID(managed_by_org_id))
    except (ValueError, TypeError):
        raise ValueError(f"Invalid organization ID: {managed_by_org_id}")

    # ManagedOrganization schema (additionalProperties: false)
    # Required: name, address_line1, zip, town, country_code, managed_by_organization_id
    body: dict = {
        "name": name[:50] if len(name) > 50 else name,
        "address_line1": address_line1 or "N/A",
        "zip": zip_code or "00000",
        "town": town or "N/A",
        "country_code": country_code,
        "managed_by_organization_id": managed_by_org_id,
    }
    if tax_number:
        body["tax_number"] = tax_number

    logger.info("Creating managed org: %s (parent: %s)", name, managed_by_org_id)
    return await _mgmt_request("POST", "/organizations", json_body=body)


async def enable_organization_env(org_id: str, env: str = "TEST") -> dict:
    """Enable TEST or LIVE environment for an organization."""
    return await _mgmt_request(
        "POST", f"/organizations/{org_id}/enable-env", json_body={"env": env}
    )


async def create_api_key_for_org(
    org_id: str, name: str = "gastropilot", managed_by_org_id: str | None = None
) -> dict:
    """Create an API key for a managed organization."""
    import re

    # Name must match ^[a-z0-9\-]{3,30}$
    safe_name = re.sub(r"[^a-z0-9\-]", "", name.lower())[:30]
    if len(safe_name) < 3:
        safe_name = "gastropilot"

    body: dict = {"name": safe_name, "status": "enabled"}
    if managed_by_org_id:
        body["managed_by_organization_id"] = managed_by_org_id

    return await _mgmt_request("POST", f"/organizations/{org_id}/api-keys", json_body=body)


async def provision_tenant_organization(
    restaurant_name: str,
    restaurant_address: str = "",
    restaurant_zip: str = "",
    restaurant_city: str = "",
    restaurant_tax_number: str = "",
) -> dict:
    """Full provisioning: create org → enable env → create API key.

    Returns dict with org_id, api_key, api_secret.
    """
    # 1. Create managed organization
    org_resp = await create_managed_organization(
        name=restaurant_name,
        address_line1=restaurant_address,
        zip_code=restaurant_zip,
        town=restaurant_city,
        tax_number=restaurant_tax_number,
    )
    org_id = org_resp["_id"]

    # 2. Enable environment (optional — may already be active)
    env = "TEST" if settings.FISKALY_TEST_MODE else "LIVE"
    try:
        await enable_organization_env(org_id, env)
    except httpx.HTTPError as exc:
        logger.warning("enable-env for org %s failed (non-critical): %s", org_id, exc)

    # 3. Create API key for the org (managed key needs parent org reference)
    master_org_id = org_resp.get("managed_by_organization_id") or await get_master_org_id()
    safe_name = f"gp-{restaurant_name[:20].lower().replace(' ', '-')}"
    key_resp = await create_api_key_for_org(org_id, safe_name, managed_by_org_id=master_org_id)

    return {
        "org_id": org_id,
        "api_key": key_resp["key"],
        "api_secret": key_resp.get("secret", ""),
    }


# ---------------------------------------------------------------------------
# TSS lifecycle (uses per-tenant credentials when available)
# ---------------------------------------------------------------------------


async def create_tss(config: FiskalyTssConfig | None, tss_id: uuid.UUID) -> dict:
    if config and config.fiskaly_api_key:
        return await _tenant_request(config, "PUT", f"/tss/{tss_id}", json_body={})
    return await _request("PUT", f"/tss/{tss_id}", json_body={})


async def update_tss_state(config: FiskalyTssConfig | None, tss_id: uuid.UUID, state: str) -> dict:
    if config and config.fiskaly_api_key:
        return await _tenant_request(config, "PATCH", f"/tss/{tss_id}", json_body={"state": state})
    return await _request("PATCH", f"/tss/{tss_id}", json_body={"state": state})


async def change_admin_pin(
    config: FiskalyTssConfig | None, tss_id: uuid.UUID, admin_puk: str, new_admin_pin: str
) -> dict:
    body = {"admin_puk": admin_puk, "new_admin_pin": new_admin_pin}
    if config and config.fiskaly_api_key:
        return await _tenant_request(config, "PATCH", f"/tss/{tss_id}/admin", json_body=body)
    return await _request("PATCH", f"/tss/{tss_id}/admin", json_body=body)


async def admin_authenticate(
    config: FiskalyTssConfig | None, tss_id: uuid.UUID, admin_pin: str
) -> dict:
    body = {"admin_pin": admin_pin}
    if config and config.fiskaly_api_key:
        return await _tenant_request(config, "POST", f"/tss/{tss_id}/admin/auth", json_body=body)
    return await _request("POST", f"/tss/{tss_id}/admin/auth", json_body=body)


async def admin_logout(config: FiskalyTssConfig | None, tss_id: uuid.UUID) -> dict:
    if config and config.fiskaly_api_key:
        return await _tenant_request(config, "POST", f"/tss/{tss_id}/admin/logout")
    return await _request("POST", f"/tss/{tss_id}/admin/logout")


async def register_client(
    config: FiskalyTssConfig | None, tss_id: uuid.UUID, client_id: uuid.UUID, serial_number: str
) -> dict:
    body = {"serial_number": serial_number}
    if config and config.fiskaly_api_key:
        return await _tenant_request(
            config, "PUT", f"/tss/{tss_id}/client/{client_id}", json_body=body
        )
    return await _request("PUT", f"/tss/{tss_id}/client/{client_id}", json_body=body)


async def create_and_initialize_tss(config: FiskalyTssConfig | None, admin_pin: str) -> dict:
    """Full TSS setup using per-tenant or master credentials."""
    tss_id = uuid.uuid4()
    client_id = uuid.uuid4()
    client_serial_number = f"GastroPilot-ERS-{client_id.hex[:12]}"

    create_resp = await create_tss(config, tss_id)
    admin_puk = create_resp["admin_puk"]

    await update_tss_state(config, tss_id, "UNINITIALIZED")
    await change_admin_pin(config, tss_id, admin_puk, admin_pin)
    await admin_authenticate(config, tss_id, admin_pin)
    init_resp = await update_tss_state(config, tss_id, "INITIALIZED")
    await register_client(config, tss_id, client_id, client_serial_number)

    try:
        await admin_logout(config, tss_id)
    except httpx.HTTPError:
        logger.warning("Admin logout failed (non-critical)")

    return {
        "tss_id": tss_id,
        "client_id": client_id,
        "client_serial_number": client_serial_number,
        "tss_serial_number": init_resp.get("serial_number", ""),
        "admin_puk": admin_puk,
    }


# ---------------------------------------------------------------------------
# Transaction signing
# ---------------------------------------------------------------------------


def _build_receipt_payload(order: Order, items: list[OrderItem], payment_type: str) -> dict:
    amounts_by_rate: dict[float, float] = defaultdict(float)
    for item in items:
        if item.status == "canceled":
            continue
        amounts_by_rate[item.tax_rate] += item.total_price

    subtotal = sum(amounts_by_rate.values())
    discount = order.discount_amount or 0.0
    if subtotal > 0 and discount > 0:
        ratio = discount / subtotal
        amounts_by_rate = {rate: amount * (1 - ratio) for rate, amount in amounts_by_rate.items()}

    vat_rate_map = {
        0.19: "NORMAL",
        0.07: "REDUCED_1",
        0.107: "SPECIAL_RATE_1",
        0.055: "SPECIAL_RATE_2",
        0.0: "NULL",
    }

    amounts_per_vat_rate = [
        {"vat_rate": vat_rate_map.get(rate, "NORMAL"), "amount": f"{amount:.2f}"}
        for rate, amount in amounts_by_rate.items()
    ]

    # § 6 KassenSichV: Storno-Beleg bei Stornierung
    is_cancellation = order.status == "canceled"
    total = order.total or 0.0

    # Bei Split-Payments: alle Zahlungsarten abbilden (Fix 5)
    amounts_per_payment_type = []
    if order.split_payments and isinstance(order.split_payments, list):
        for sp in order.split_payments:
            sp_method = sp.get("method", "cash")
            sp_amount = float(sp.get("amount", 0)) + float(sp.get("tip_amount", 0))
            sp_type = "CASH" if sp_method == "cash" else "NON_CASH"
            amounts_per_payment_type.append(
                {"payment_type": sp_type, "amount": f"{sp_amount:.2f}", "currency_code": "EUR"}
            )
    if not amounts_per_payment_type:
        amounts_per_payment_type.append(
            {"payment_type": payment_type, "amount": f"{total:.2f}", "currency_code": "EUR"}
        )

    return {
        "standard_v1": {
            "receipt": {
                "receipt_type": "CANCELLATION" if is_cancellation else "RECEIPT",
                "amounts_per_vat_rate": amounts_per_vat_rate,
                "amounts_per_payment_type": amounts_per_payment_type,
            }
        }
    }


async def sign_transaction(
    config: FiskalyTssConfig,
    tss_id: uuid.UUID,
    client_id: uuid.UUID,
    tx_id: uuid.UUID,
    state: str,
    schema: dict | None = None,
    tx_revision: int = 1,
) -> dict:
    body: dict = {"state": state, "client_id": str(client_id)}
    if schema:
        body["schema"] = schema
    return await _tenant_request(
        config, "PUT", f"/tss/{tss_id}/tx/{tx_id}?tx_revision={tx_revision}", json_body=body
    )


async def start_and_finish_receipt(
    config: FiskalyTssConfig,
    tss_id: uuid.UUID,
    client_id: uuid.UUID,
    order: Order,
    items: list[OrderItem],
    payment_type: str,
) -> dict:
    tx_id = uuid.uuid4()
    schema = _build_receipt_payload(order, items, payment_type)
    await sign_transaction(config, tss_id, client_id, tx_id, "ACTIVE", schema, tx_revision=1)
    return await sign_transaction(
        config, tss_id, client_id, tx_id, "FINISHED", schema, tx_revision=2
    )


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


async def trigger_export(
    config: FiskalyTssConfig,
    tss_id: uuid.UUID,
    export_id: uuid.UUID,
    start_date: int | None = None,
    end_date: int | None = None,
) -> dict:
    params = []
    if start_date is not None:
        params.append(f"start_date={start_date}")
    if end_date is not None:
        params.append(f"end_date={end_date}")
    qs = f"?{'&'.join(params)}" if params else ""
    return await _tenant_request(
        config, "PUT", f"/tss/{tss_id}/export/{export_id}{qs}", json_body={}
    )


async def get_export(config: FiskalyTssConfig, tss_id: uuid.UUID, export_id: uuid.UUID) -> dict:
    return await _tenant_request(config, "GET", f"/tss/{tss_id}/export/{export_id}")


async def get_export_file(
    config: FiskalyTssConfig, tss_id: uuid.UUID, export_id: uuid.UUID
) -> bytes:
    api_key = config.fiskaly_api_key or settings.FISKALY_API_KEY
    api_secret = config.fiskaly_api_secret or settings.FISKALY_API_SECRET
    token = await _ensure_token_for(settings.FISKALY_BASE_URL, api_key, api_secret)
    url = f"{settings.FISKALY_BASE_URL}/tss/{tss_id}/export/{export_id}/file"
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code >= 400:
            logger.error("fiskaly export file download → %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()
        return resp.content


async def list_exports(config: FiskalyTssConfig, tss_id: uuid.UUID) -> list[dict]:
    return await _tenant_request(config, "GET", f"/tss/{tss_id}/export")


async def cancel_export(config: FiskalyTssConfig, tss_id: uuid.UUID, export_id: uuid.UUID) -> dict:
    return await _tenant_request(config, "DELETE", f"/tss/{tss_id}/export/{export_id}")


# ---------------------------------------------------------------------------
# eReceipt API (https://receipt.fiskaly.com/api/v1)
# ---------------------------------------------------------------------------

RECEIPT_BASE_URL = "https://receipt.fiskaly.com/api/v1"


async def _receipt_request(
    api_key: str, api_secret: str, method: str, path: str, json_body: dict | None = None
) -> dict:
    return await _api_request(RECEIPT_BASE_URL, api_key, api_secret, method, path, json_body)


def _build_receipt_ekabs(
    order: Order,
    items: list[OrderItem],
    tse_data: FiskalyTransaction,
    restaurant_name: str,
    restaurant_address: str,
    restaurant_tax_number: str,
    payment_type: str,
) -> dict:
    lines = []
    for item in items:
        if item.status == "canceled":
            continue
        vat_pct = f"{item.tax_rate * 100:.2f}"
        lines.append(
            {
                "text": item.item_name,
                "item": {
                    "number": str(item.menu_item_id or item.id),
                    "quantity": f"{item.quantity}.00",
                    "price_per_unit": f"{item.unit_price:.2f}",
                    "full_amount": f"{item.total_price:.2f}",
                },
                "vat_amounts": [{"percentage": vat_pct, "incl_vat": f"{item.total_price:.2f}"}],
                "sort_order": item.sort_order,
            }
        )

    vat_buckets: dict[float, dict] = {}
    for item in items:
        if item.status == "canceled":
            continue
        rate = item.tax_rate
        if rate not in vat_buckets:
            vat_buckets[rate] = {"incl": 0.0, "excl": 0.0, "vat": 0.0}
        gross = item.total_price
        net = gross / (1 + rate)
        vat_buckets[rate]["incl"] += gross
        vat_buckets[rate]["excl"] += net
        vat_buckets[rate]["vat"] += gross - net

    vat_amounts = [
        {
            "percentage": f"{rate * 100:.2f}",
            "incl_vat": f"{b['incl']:.2f}",
            "excl_vat": f"{b['excl']:.2f}",
            "vat": f"{b['vat']:.2f}",
        }
        for rate, b in vat_buckets.items()
    ]

    payment_name = "CASH" if payment_type == "CASH" else "CARD"
    total = order.total or 0.0
    addr_parts = restaurant_address.split(",") if restaurant_address else ["", ""]
    street = addr_parts[0].strip() if len(addr_parts) > 0 else ""
    city_postal = addr_parts[1].strip() if len(addr_parts) > 1 else ""

    security: dict = {}
    if tse_data and tse_data.tx_state == "FINISHED":
        security = {
            "tse": {
                "tss_serial_number": tse_data.tss_serial_number or "",
                "client_serial_number": tse_data.client_serial_number or "",
                "number": tse_data.tx_number,
                "time_start": tse_data.time_start,
                "time_end": tse_data.time_end,
                "qr_code_data": tse_data.qr_code_data or "",
                "signature": {
                    "value": tse_data.signature_value or "",
                    "algorithm": tse_data.signature_algorithm or "ecdsa-plain-SHA256",
                    "public_key": "",
                },
                "log": {"timestamp_format": "unixTime"},
            }
        }

    receipt_number = order.order_number or str(order.id)[:8]
    opened_ts = int(order.opened_at.timestamp()) if order.opened_at else int(time.time())

    return {
        "schema": {
            "ekabs_v0": {
                "head": {
                    "number": receipt_number,
                    "date": opened_ts,
                    "seller": {
                        "name": restaurant_name,
                        "address": {"street": street, "city": city_postal, "country_code": "DEU"},
                        "tax_number": restaurant_tax_number,
                    },
                },
                "data": {
                    "currency": "EUR",
                    "full_amount_incl_vat": f"{total:.2f}",
                    "lines": lines,
                    "payment_types": [{"name": payment_name, "amount": f"{total:.2f}"}],
                    "vat_amounts": vat_amounts,
                },
                "security": security,
                "language": "de",
                "misc": {"footer_text": "Vielen Dank für Ihren Besuch!"},
            }
        }
    }


async def create_receipt(
    config: FiskalyTssConfig,
    order: Order,
    items: list[OrderItem],
    tse_data: FiskalyTransaction,
    restaurant_name: str,
    restaurant_address: str,
    restaurant_tax_number: str,
    payment_type: str,
) -> dict:
    api_key = config.fiskaly_api_key or settings.FISKALY_API_KEY
    api_secret = config.fiskaly_api_secret or settings.FISKALY_API_SECRET
    receipt_id = str(uuid.uuid4())
    body = _build_receipt_ekabs(
        order,
        items,
        tse_data,
        restaurant_name,
        restaurant_address,
        restaurant_tax_number,
        payment_type,
    )
    return await _receipt_request(
        api_key, api_secret, "PUT", f"/receipt/{receipt_id}", json_body=body
    )


# ---------------------------------------------------------------------------
# High-level orchestration
# ---------------------------------------------------------------------------


def resolve_payment_type(payment_method: str | None) -> str:
    if not payment_method:
        return "NON_CASH"
    method_lower = payment_method.lower()
    if "cash" in method_lower or "bar" in method_lower:
        return "CASH"
    return "NON_CASH"


async def sign_order_receipt(
    db: AsyncSession,
    order: Order,
    payment_type: str | None = None,
    items: list[OrderItem] | None = None,
) -> FiskalyTransaction | None:
    if not _is_configured():
        return None

    result = await db.execute(
        select(FiskalyTssConfig).where(
            FiskalyTssConfig.tenant_id == order.tenant_id,
            FiskalyTssConfig.state == "INITIALIZED",
        )
    )
    tss_config = result.scalar_one_or_none()
    if not tss_config:
        logger.debug("No initialized TSS config for tenant %s", order.tenant_id)
        return None

    if items is None:
        items_result = await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))
        items = list(items_result.scalars().all())

    if not items:
        logger.debug("No items for order %s, skipping TSE signing", order.id)
        return None

    if payment_type is None:
        payment_type = resolve_payment_type(order.payment_method)

    tx_record = FiskalyTransaction(
        tenant_id=order.tenant_id,
        order_id=order.id,
        tss_id=tss_config.tss_id,
        tx_id=uuid.uuid4(),
        receipt_type="RECEIPT",
    )

    try:
        resp = await start_and_finish_receipt(
            config=tss_config,
            tss_id=tss_config.tss_id,
            client_id=tss_config.client_id,
            order=order,
            items=items,
            payment_type=payment_type,
        )
        tx_record.tx_id = uuid.UUID(resp["_id"])
        tx_record.tx_number = resp.get("number")
        tx_record.tx_state = resp.get("state", "FINISHED")
        tx_record.time_start = resp.get("time_start")
        tx_record.time_end = resp.get("time_end")
        tx_record.qr_code_data = resp.get("qr_code_data")
        tx_record.tss_serial_number = resp.get("tss_serial_number")
        tx_record.client_serial_number = resp.get("client_serial_number")
        tx_record.raw_response = resp
        sig = resp.get("signature", {})
        tx_record.signature_value = sig.get("value")
        tx_record.signature_algorithm = sig.get("algorithm")
        tx_record.signature_counter = sig.get("counter")
    except Exception as exc:
        logger.error("fiskaly signing failed for order %s: %s", order.id, exc)
        tx_record.error = str(exc)
        tx_record.tx_state = "ERROR"

    db.add(tx_record)
    await db.flush()
    return tx_record


# ---------------------------------------------------------------------------
# DSFinV-K API (https://dsfinvk.fiskaly.com/api/v1)
# ---------------------------------------------------------------------------


async def _dsfinvk_request(
    api_key: str, api_secret: str, method: str, path: str, json_body: dict | None = None
) -> dict:
    """Request against the fiskaly DSFinV-K API."""
    return await _api_request(
        settings.FISKALY_DSFINVK_URL, api_key, api_secret, method, path, json_body
    )


async def _dsfinvk_tenant_request(
    config: FiskalyTssConfig, method: str, path: str, json_body: dict | None = None
) -> dict:
    """DSFinV-K request with per-tenant credentials."""
    api_key = config.fiskaly_api_key or settings.FISKALY_API_KEY
    api_secret = config.fiskaly_api_secret or settings.FISKALY_API_SECRET
    return await _dsfinvk_request(api_key, api_secret, method, path, json_body)


async def dsfinvk_get_cash_register(config: FiskalyTssConfig, client_id: uuid.UUID) -> dict:
    """Get cash register details from DSFinV-K."""
    return await _dsfinvk_tenant_request(config, "GET", f"/cash_registers/{client_id}")


async def dsfinvk_upsert_cash_register(
    config: FiskalyTssConfig,
    client_id: uuid.UUID,
    body: dict,
) -> dict:
    """Create or update a cash register in DSFinV-K."""
    return await _dsfinvk_tenant_request(
        config, "PUT", f"/cash_registers/{client_id}", json_body=body
    )


async def dsfinvk_upsert_vat_definition(
    config: FiskalyTssConfig,
    vat_definition_export_id: int,
    body: dict,
) -> dict:
    """Create or update a VAT definition in DSFinV-K."""
    return await _dsfinvk_tenant_request(
        config, "PUT", f"/vat_definitions/{vat_definition_export_id}", json_body=body
    )


async def dsfinvk_insert_cash_point_closing(
    config: FiskalyTssConfig, closing_id: uuid.UUID, body: dict
) -> dict:
    """Insert a cash point closing (Kassenabschluss) in DSFinV-K."""
    return await _dsfinvk_tenant_request(
        config, "PUT", f"/cash_point_closings/{closing_id}", json_body=body
    )


async def dsfinvk_get_cash_point_closing(
    config: FiskalyTssConfig, closing_id: uuid.UUID
) -> dict:
    """Get a single cash point closing."""
    return await _dsfinvk_tenant_request(config, "GET", f"/cash_point_closings/{closing_id}")


async def dsfinvk_list_cash_point_closings(
    config: FiskalyTssConfig,
    client_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List cash point closings."""
    params = [f"limit={limit}", f"offset={offset}", "order=desc", "order_by=time_creation"]
    if client_id:
        params.append(f"client_id={client_id}")
    qs = "&".join(params)
    return await _dsfinvk_tenant_request(config, "GET", f"/cash_point_closings?{qs}")


async def dsfinvk_delete_cash_point_closing(
    config: FiskalyTssConfig, closing_id: uuid.UUID
) -> None:
    """Delete a cash point closing."""
    api_key = config.fiskaly_api_key or settings.FISKALY_API_KEY
    api_secret = config.fiskaly_api_secret or settings.FISKALY_API_SECRET
    token = await _ensure_token_for(settings.FISKALY_DSFINVK_URL, api_key, api_secret)
    url = f"{settings.FISKALY_DSFINVK_URL}/cash_point_closings/{closing_id}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.delete(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code >= 400:
            logger.error("DSFinV-K delete closing %s → %s: %s", closing_id, resp.status_code, resp.text)
            resp.raise_for_status()


async def dsfinvk_trigger_export(
    config: FiskalyTssConfig, export_id: uuid.UUID, body: dict
) -> dict:
    """Trigger a DSFinV-K export."""
    return await _dsfinvk_tenant_request(
        config, "PUT", f"/exports/{export_id}", json_body=body
    )


async def dsfinvk_get_export(config: FiskalyTssConfig, export_id: uuid.UUID) -> dict:
    """Get a DSFinV-K export status."""
    return await _dsfinvk_tenant_request(config, "GET", f"/exports/{export_id}")


async def dsfinvk_download_export(config: FiskalyTssConfig, export_id: uuid.UUID) -> bytes:
    """Download a completed DSFinV-K export file."""
    api_key = config.fiskaly_api_key or settings.FISKALY_API_KEY
    api_secret = config.fiskaly_api_secret or settings.FISKALY_API_SECRET
    token = await _ensure_token_for(settings.FISKALY_DSFINVK_URL, api_key, api_secret)
    url = f"{settings.FISKALY_DSFINVK_URL}/exports/{export_id}/download"
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code >= 400:
            logger.error(
                "DSFinV-K export download %s → %s: %s", export_id, resp.status_code, resp.text
            )
            resp.raise_for_status()
        return resp.content


async def dsfinvk_list_exports(
    config: FiskalyTssConfig,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List DSFinV-K exports."""
    return await _dsfinvk_tenant_request(
        config, "GET", f"/exports?limit={limit}&offset={offset}&order=desc&order_by=time_creation"
    )


# ---------------------------------------------------------------------------
# DSFinV-K VAT definition IDs (convention)
# ---------------------------------------------------------------------------

DSFINVK_VAT_DEFINITIONS = {
    0.19: {"export_id": 1000, "percentage": 19.0, "description": "Allgemeiner Steuersatz"},
    0.07: {"export_id": 1001, "percentage": 7.0, "description": "Ermäßigter Steuersatz"},
    0.107: {"export_id": 1002, "percentage": 10.7, "description": "Durchschnittsatz (§ 24 Abs. 1 Nr. 3 UStG)"},
    0.055: {"export_id": 1003, "percentage": 5.5, "description": "Durchschnittsatz (§ 24 Abs. 1 Nr. 1 UStG)"},
    0.0: {"export_id": 1004, "percentage": 0.0, "description": "Nicht steuerbar"},
}


async def ensure_dsfinvk_vat_definitions(config: FiskalyTssConfig) -> None:
    """Ensure all standard VAT definitions exist in DSFinV-K."""
    for _rate, vat_def in DSFINVK_VAT_DEFINITIONS.items():
        try:
            await dsfinvk_upsert_vat_definition(
                config,
                vat_def["export_id"],
                {"percentage": vat_def["percentage"], "description": vat_def["description"]},
            )
        except httpx.HTTPError as exc:
            logger.warning("VAT definition %s upsert failed: %s", vat_def["export_id"], exc)


# ---------------------------------------------------------------------------
# DSFinV-K cash register setup
# ---------------------------------------------------------------------------


async def ensure_dsfinvk_cash_register(config: FiskalyTssConfig) -> dict:
    """Ensure the cash register exists in DSFinV-K."""
    body = {
        "cash_register_type": {"type": "MASTER", "tss_id": str(config.tss_id)},
        "brand": "GastroPilot",
        "model": "Cloud POS",
        "software": {"brand": "GastroPilot"},
        "base_currency_code": "EUR",
    }
    return await dsfinvk_upsert_cash_register(config, config.client_id, body)


# ---------------------------------------------------------------------------
# Build cash point closing payload from daily orders
# ---------------------------------------------------------------------------

PAYMENT_TYPE_EXPORT_IDS = {
    "CASH": "Bar",
    "NON_CASH": "Unbar",
}


def _resolve_dsfinvk_payment_type(payment_method: str | None) -> str:
    """Map payment method to DSFinV-K payment type enum."""
    if not payment_method:
        return "Unbar"
    method_lower = payment_method.lower()
    if "cash" in method_lower or "bar" in method_lower:
        return "Bar"
    if "ec" in method_lower or "giro" in method_lower or "debit" in method_lower:
        return "ECKarte"
    if "credit" in method_lower or "kredit" in method_lower:
        return "Kreditkarte"
    if "paypal" in method_lower or "apple" in method_lower or "google" in method_lower:
        return "ElZahlungsdienstleister"
    return "Unbar"


def _build_cash_point_closing_payload(
    closing_id: uuid.UUID,
    business_date: str,
    closing_number: int,
    orders: list[Order],
    order_items_map: dict[uuid.UUID, list[OrderItem]],
    transactions: list[FiskalyTransaction],
    config: FiskalyTssConfig,
) -> dict:
    """Build the full cash point closing payload for DSFinV-K API.

    Schema: PUT /cash_point_closings/{closing_id}
    Required top-level: client_id, cash_point_closing_export_id, head
    """
    tx_by_order: dict[uuid.UUID, FiskalyTransaction] = {}
    for tx in transactions:
        if tx.tx_state == "FINISHED":
            tx_by_order[tx.order_id] = tx

    # Aggregate totals
    payment_cash = 0.0
    payment_non_cash = 0.0
    total_payment = 0.0
    first_tx_export_id: str | None = None
    last_tx_export_id: str | None = None

    dsfinvk_transactions = []
    tx_counter = 0

    for order in orders:
        items = order_items_map.get(order.id, [])
        tx = tx_by_order.get(order.id)
        if not tx:
            continue

        tx_counter += 1
        order_total = float(order.total or 0)
        pm = resolve_payment_type(order.payment_method)
        if pm == "CASH":
            payment_cash += order_total
        else:
            payment_non_cash += order_total
        total_payment += order_total

        tx_export_id = str(tx.tx_number or tx_counter)
        if first_tx_export_id is None:
            first_tx_export_id = tx_export_id
        last_tx_export_id = tx_export_id

        # Build line items
        tx_lines = []
        line_counter = 0
        for item in items:
            if item.status == "canceled":
                continue
            line_counter += 1
            rate = item.tax_rate
            vat_def = DSFINVK_VAT_DEFINITIONS.get(rate, DSFINVK_VAT_DEFINITIONS[0.19])
            gross = float(item.total_price)
            net = gross / (1 + rate) if rate > 0 else gross
            vat_amt = gross - net
            tx_lines.append({
                "business_case": {
                    "type": "Umsatz",
                    "amounts_per_vat_id": [
                        {
                            "vat_definition_export_id": vat_def["export_id"],
                            "incl_vat": round(gross, 2),
                            "excl_vat": round(net, 2),
                            "vat": round(vat_amt, 2),
                        }
                    ],
                },
                "lineitem_export_id": f"{tx_export_id}-{line_counter}",
                "storno": False,
                "text": item.item_name or f"Artikel {line_counter}",
                "item": {
                    "number": str(item.menu_item_id or item.id),
                    "quantity": float(item.quantity),
                    "price_per_unit": round(float(item.unit_price), 2),
                },
            })

        if not tx_lines:
            continue

        # Security
        security: dict
        if tx.tx_state == "FINISHED" and tx.raw_response:
            security = {"tss_tx_id": str(tx.tx_id)}
        else:
            security = {"error_message": tx.error or "TSE transaction not finished"}

        ts_start = tx.time_start or (
            int(order.opened_at.timestamp()) if order.opened_at else int(time.time())
        )
        ts_end = tx.time_end or int(time.time())

        # Per-transaction payment
        dsfinvk_payment_type = _resolve_dsfinvk_payment_type(order.payment_method)

        dsfinvk_transactions.append({
            "head": {
                "type": "Beleg",
                "storno": False,
                "number": tx.tx_number or tx_counter,
                "timestamp_start": ts_start,
                "timestamp_end": ts_end,
                "transaction_export_id": tx_export_id,
                "closing_client_id": str(config.client_id),
            },
            "data": {
                "full_amount_incl_vat": round(order_total, 2),
                "payment_types": [
                    {
                        "type": dsfinvk_payment_type,
                        "currency_code": "EUR",
                        "amount": round(order_total, 2),
                    }
                ],
                "amounts_per_vat_id": [
                    {
                        "vat_definition_export_id": vat_def["export_id"],
                        "incl_vat": round(
                            sum(
                                float(i.total_price) for i in items
                                if i.status != "canceled"
                                and DSFINVK_VAT_DEFINITIONS.get(
                                    i.tax_rate, DSFINVK_VAT_DEFINITIONS[0.19]
                                )["export_id"] == vat_def["export_id"]
                            ),
                            2,
                        ),
                        "excl_vat": round(
                            sum(
                                float(i.total_price) / (1 + i.tax_rate)
                                if i.tax_rate > 0 else float(i.total_price)
                                for i in items
                                if i.status != "canceled"
                                and DSFINVK_VAT_DEFINITIONS.get(
                                    i.tax_rate, DSFINVK_VAT_DEFINITIONS[0.19]
                                )["export_id"] == vat_def["export_id"]
                            ),
                            2,
                        ),
                        "vat": round(
                            sum(
                                float(i.total_price)
                                - float(i.total_price) / (1 + i.tax_rate)
                                if i.tax_rate > 0 else 0.0
                                for i in items
                                if i.status != "canceled"
                                and DSFINVK_VAT_DEFINITIONS.get(
                                    i.tax_rate, DSFINVK_VAT_DEFINITIONS[0.19]
                                )["export_id"] == vat_def["export_id"]
                            ),
                            2,
                        ),
                    }
                    for vat_def in {
                        DSFINVK_VAT_DEFINITIONS.get(
                            i.tax_rate, DSFINVK_VAT_DEFINITIONS[0.19]
                        )["export_id"]: DSFINVK_VAT_DEFINITIONS.get(
                            i.tax_rate, DSFINVK_VAT_DEFINITIONS[0.19]
                        )
                        for i in items if i.status != "canceled"
                    }.values()
                ],
                "lines": tx_lines,
            },
            "security": security,
        })

    # Cash statement: business_cases + payment
    business_cases = []
    vat_totals: dict[int, dict[str, float]] = {}
    for order in orders:
        for item in order_items_map.get(order.id, []):
            if item.status == "canceled":
                continue
            rate = item.tax_rate
            vd = DSFINVK_VAT_DEFINITIONS.get(rate, DSFINVK_VAT_DEFINITIONS[0.19])
            eid = vd["export_id"]
            gross = float(item.total_price)
            net = gross / (1 + rate) if rate > 0 else gross
            vat_amt = gross - net
            if eid not in vat_totals:
                vat_totals[eid] = {"incl_vat": 0.0, "excl_vat": 0.0, "vat": 0.0}
            vat_totals[eid]["incl_vat"] += gross
            vat_totals[eid]["excl_vat"] += net
            vat_totals[eid]["vat"] += vat_amt

    business_cases.append({
        "type": "Umsatz",
        "amounts_per_vat_id": [
            {
                "vat_definition_export_id": vid,
                "incl_vat": round(t["incl_vat"], 2),
                "excl_vat": round(t["excl_vat"], 2),
                "vat": round(t["vat"], 2),
            }
            for vid, t in vat_totals.items()
        ],
    })

    payment_types = []
    if payment_cash != 0:
        payment_types.append({
            "type": "Bar",
            "currency_code": "EUR",
            "amount": round(payment_cash, 2),
        })
    if payment_non_cash != 0:
        payment_types.append({
            "type": "Unbar",
            "currency_code": "EUR",
            "amount": round(payment_non_cash, 2),
        })
    if not payment_types:
        payment_types.append({
            "type": "Bar",
            "currency_code": "EUR",
            "amount": 0.0,
        })

    cash_amounts_by_currency = [{"currency_code": "EUR", "amount": round(payment_cash, 2)}]

    now_ts = int(time.time())

    return {
        "client_id": str(config.client_id),
        "cash_point_closing_export_id": closing_number,
        "head": {
            "export_creation_date": now_ts,
            "first_transaction_export_id": first_tx_export_id,
            "last_transaction_export_id": last_tx_export_id,
            "business_date": business_date,
        },
        "cash_statement": {
            "business_cases": business_cases,
            "payment": {
                "full_amount": round(total_payment, 2),
                "cash_amount": round(payment_cash, 2),
                "cash_amounts_by_currency": cash_amounts_by_currency,
                "payment_types": payment_types,
            },
        },
        "transactions": dsfinvk_transactions,
    }


# ---------------------------------------------------------------------------
# High-level: perform daily closing
# ---------------------------------------------------------------------------


async def perform_daily_closing(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    business_date: str,
    is_automatic: bool = False,
) -> FiskalyCashPointClosing:
    """Perform a full daily cash point closing for DSFinV-K.

    1. Load TSS config
    2. Ensure cash register & VAT definitions exist in DSFinV-K
    3. Load all paid orders + their TSE transactions for the given date
    4. Build & submit the cash point closing payload
    5. Persist the result
    """
    # 1. TSS config
    result = await db.execute(
        select(FiskalyTssConfig).where(
            FiskalyTssConfig.tenant_id == tenant_id,
            FiskalyTssConfig.state == "INITIALIZED",
        )
    )
    tss_config = result.scalar_one_or_none()
    if not tss_config:
        raise ValueError("Keine initialisierte TSS-Konfiguration gefunden")

    # 2. Ensure master data
    try:
        await ensure_dsfinvk_cash_register(tss_config)
        await ensure_dsfinvk_vat_definitions(tss_config)
    except Exception as exc:
        logger.warning("DSFinV-K master data setup warning: %s", exc)

    # 3. Load orders for the day
    from datetime import UTC
    from datetime import datetime as dt

    day_start = dt.fromisoformat(f"{business_date}T00:00:00").replace(tzinfo=UTC)
    day_end = dt.fromisoformat(f"{business_date}T23:59:59").replace(tzinfo=UTC)

    orders_result = await db.execute(
        select(Order).where(
            Order.tenant_id == tenant_id,
            Order.payment_status == "paid",
            Order.opened_at >= day_start,
            Order.opened_at <= day_end,
        )
    )
    orders = list(orders_result.scalars().all())

    if not orders:
        raise ValueError(f"Keine bezahlten Bestellungen am {business_date}")

    order_ids = [o.id for o in orders]

    # Load items
    items_result = await db.execute(
        select(OrderItem).where(OrderItem.order_id.in_(order_ids))
    )
    all_items = list(items_result.scalars().all())
    order_items_map: dict[uuid.UUID, list[OrderItem]] = defaultdict(list)
    for item in all_items:
        order_items_map[item.order_id].append(item)

    # Load TSE transactions
    tx_result = await db.execute(
        select(FiskalyTransaction).where(
            FiskalyTransaction.tenant_id == tenant_id,
            FiskalyTransaction.order_id.in_(order_ids),
        )
    )
    transactions = list(tx_result.scalars().all())

    # 4. Check for existing closing
    existing_result = await db.execute(
        select(FiskalyCashPointClosing).where(
            FiskalyCashPointClosing.tenant_id == tenant_id,
            FiskalyCashPointClosing.business_date == business_date,
            FiskalyCashPointClosing.state.notin_(["ERROR", "DELETED"]),
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        raise ValueError(f"Tagesabschluss für {business_date} existiert bereits (ID: {existing.closing_id})")

    # Count existing closings for numbering
    count_result = await db.execute(
        select(FiskalyCashPointClosing).where(
            FiskalyCashPointClosing.tenant_id == tenant_id,
        )
    )
    closing_number = len(count_result.scalars().all()) + 1

    # Build payload
    closing_id = uuid.uuid4()
    payload = _build_cash_point_closing_payload(
        closing_id=closing_id,
        business_date=business_date,
        closing_number=closing_number,
        orders=orders,
        order_items_map=order_items_map,
        transactions=transactions,
        config=tss_config,
    )

    # Calculate totals for local record
    total_amount = sum(float(o.total or 0) for o in orders)
    total_cash = sum(
        float(o.total or 0) for o in orders
        if resolve_payment_type(o.payment_method) == "CASH"
    )
    total_non_cash = total_amount - total_cash

    # 5. Submit to DSFinV-K
    record = FiskalyCashPointClosing(
        tenant_id=tenant_id,
        closing_id=closing_id,
        business_date=business_date,
        state="PENDING",
        cash_register_export_id=str(tss_config.client_id)[:50],
        total_amount=round(total_amount, 2),
        total_cash=round(total_cash, 2),
        total_non_cash=round(total_non_cash, 2),
        transaction_count=len(payload["transactions"]),
        is_automatic=is_automatic,
        raw_request=payload,
    )

    try:
        resp = await dsfinvk_insert_cash_point_closing(tss_config, closing_id, payload)
        record.state = resp.get("state", "WORKING")
        record.raw_response = resp
    except Exception as exc:
        logger.error("DSFinV-K cash point closing failed for %s: %s", business_date, exc)
        record.state = "ERROR"
        record.error = str(exc)

    db.add(record)
    await db.flush()
    return record

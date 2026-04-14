"""Receipt PDF generation: Kassenbeleg, Bewirtungsbeleg, Bewirtungsrechnung.

All documents comply with German tax law requirements:
- § 14 UStG (invoice requirements)
- § 14a UStG (special cases)
- § 146a AO (receipt requirements / Belegausgabepflicht)
- § 4 Abs. 5 Nr. 2 EStG (hospitality receipts)
"""

from __future__ import annotations

import io
import logging
from datetime import UTC as _UTC
from datetime import datetime as dt
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_staff_or_above
from app.models.fiskaly import FiskalyTransaction
from app.models.order import Order, OrderItem

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/receipts", tags=["receipts"])

_BON_WIDTH_MM = 80
_BON_MARGIN_MM = 4


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _rl():
    """Lazy-load ReportLab modules."""
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
        from reportlab.platypus import TableStyle

        return {
            "colors": colors, "A4": A4, "getSampleStyleSheet": getSampleStyleSheet,
            "ParagraphStyle": ParagraphStyle, "mm": mm, "HRFlowable": HRFlowable,
            "Paragraph": Paragraph, "SimpleDocTemplate": SimpleDocTemplate,
            "Spacer": Spacer, "RLTable": RLTable, "TableStyle": TableStyle,
        }
    except ImportError:
        raise HTTPException(status_code=500, detail="ReportLab nicht installiert")


async def _load_order(db: AsyncSession, order_id: UUID):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Bestellung nicht gefunden")

    items_result = await db.execute(
        select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.sort_order)
    )
    items = list(items_result.scalars().all())

    tse_result = await db.execute(
        select(FiskalyTransaction)
        .where(FiskalyTransaction.order_id == order_id, FiskalyTransaction.tx_state == "FINISHED")
        .order_by(FiskalyTransaction.created_at.desc())
    )
    tse_tx = tse_result.scalars().first()

    return order, items, tse_tx


async def _load_restaurant(db: AsyncSession, tenant_id):
    """Load restaurant business data from shared DB."""
    from sqlalchemy import text

    row = await db.execute(
        text(
            "SELECT name, company_name, street, zip_code, city, country, "
            "address, phone, email, tax_number, vat_id "
            "FROM restaurants WHERE id = :tid"
        ),
        {"tid": str(tenant_id)},
    )
    r = row.mappings().first()
    if not r:
        return {
            "name": "", "company_name": "", "street": "", "zip_code": "",
            "city": "", "country": "DE", "address": "", "phone": "",
            "email": "", "tax_number": "", "vat_id": "",
        }
    return dict(r)


def _restaurant_address_block(rest: dict) -> str:
    """Build multi-line address string."""
    name = rest.get("company_name") or rest.get("name") or ""
    street = rest.get("street") or ""
    plz_city = f"{rest.get('zip_code', '')} {rest.get('city', '')}".strip()
    # Fallback to legacy address field
    if not street and not plz_city:
        return f"{name}<br/>{rest.get('address', '')}"
    parts = [name]
    if street:
        parts.append(street)
    if plz_city:
        parts.append(plz_city)
    return "<br/>".join(p for p in parts if p)


def _fmt(amount: float) -> str:
    return f"{amount:.2f} EUR"


def _active_items(items):
    return [i for i in items if i.status != "canceled"]


def _build_tse_bon(rl, tse_tx, story, style_tiny, col_w):
    """Append TSE block for thermal receipts."""
    mm = rl["mm"]
    P, S, T, TS = rl["Paragraph"], rl["Spacer"], rl["RLTable"], rl["TableStyle"]

    story.append(S(1, 2 * mm))
    story.append(P("TSE-Daten", style_tiny))
    story.append(S(1, 1 * mm))

    rows = []
    if tse_tx.tss_serial_number:
        rows.append(["TSE-SN:", tse_tx.tss_serial_number[:28] + "..."])
    if tse_tx.tx_number is not None:
        rows.append(["TX-Nr:", str(tse_tx.tx_number)])
    if tse_tx.signature_value:
        rows.append(["Signatur:", tse_tx.signature_value[:28] + "..."])
    if tse_tx.time_start:
        rows.append(["Start:", dt.fromtimestamp(tse_tx.time_start, tz=_UTC).strftime("%d.%m.%Y %H:%M:%S")])
    if tse_tx.time_end:
        rows.append(["Ende:", dt.fromtimestamp(tse_tx.time_end, tz=_UTC).strftime("%d.%m.%Y %H:%M:%S")])
    if tse_tx.client_serial_number:
        rows.append(["Kassen-ID:", tse_tx.client_serial_number])

    if rows:
        t = T(rows, colWidths=[col_w * 0.32, col_w * 0.68])
        t.setStyle(TS([
            ("FONTSIZE", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        story.append(t)

    if tse_tx.qr_code_data:
        try:
            from reportlab.graphics.barcode.qr import QrCodeWidget
            from reportlab.graphics.shapes import Drawing

            qr_size = 28 * mm
            qr = QrCodeWidget(tse_tx.qr_code_data, barWidth=qr_size, barHeight=qr_size)
            d = Drawing(qr_size, qr_size)
            d.add(qr)
            story.append(S(1, 2 * mm))
            story.append(d)
        except Exception:
            story.append(P("(QR-Code nicht verfügbar)", style_tiny))


def _build_tse_a4(rl, tse_tx, story, styles, mm):
    """Append TSE block for A4 documents."""
    P, S, T, TS = rl["Paragraph"], rl["Spacer"], rl["RLTable"], rl["TableStyle"]

    story.append(S(1, 4 * mm))
    story.append(P("TSE-Daten (§ 146a AO)", styles["Heading4"]))
    story.append(S(1, 2 * mm))

    rows = []
    if tse_tx.tss_serial_number:
        rows.append(["TSE-Seriennummer:", tse_tx.tss_serial_number[:50]])
    if tse_tx.tx_number is not None:
        rows.append(["Transaktionsnummer:", str(tse_tx.tx_number)])
    if tse_tx.signature_value:
        rows.append(["Signaturwert:", tse_tx.signature_value[:50] + "..."])
    if tse_tx.signature_algorithm:
        rows.append(["Signaturalgorithmus:", tse_tx.signature_algorithm])
    if tse_tx.time_start:
        rows.append(["Transaktionsbeginn:", dt.fromtimestamp(tse_tx.time_start, tz=_UTC).strftime("%d.%m.%Y %H:%M:%S")])
    if tse_tx.time_end:
        rows.append(["Transaktionsende:", dt.fromtimestamp(tse_tx.time_end, tz=_UTC).strftime("%d.%m.%Y %H:%M:%S")])
    if tse_tx.signature_counter is not None:
        rows.append(["Signaturzähler:", str(tse_tx.signature_counter)])
    if tse_tx.client_serial_number:
        rows.append(["Kassen-Seriennummer:", tse_tx.client_serial_number])

    if rows:
        t = T(rows, colWidths=[130, 330])
        t.setStyle(TS([("FONTSIZE", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)

    if tse_tx.qr_code_data:
        try:
            from reportlab.graphics.barcode.qr import QrCodeWidget
            from reportlab.graphics.shapes import Drawing

            qr_size = 35 * mm
            qr = QrCodeWidget(tse_tx.qr_code_data, barWidth=qr_size, barHeight=qr_size)
            d = Drawing(qr_size, qr_size)
            d.add(qr)
            story.append(S(1, 2 * mm))
            story.append(d)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 1) Kassenbeleg – 80mm thermal (§ 146a AO Belegausgabepflicht)
# ---------------------------------------------------------------------------


@router.get("/{order_id}/kassenbeleg")
async def generate_kassenbeleg(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    """Kassenbeleg gem. § 146a AO – Pflichtbeleg für jede Transaktion."""
    r = _rl()
    mm = r["mm"]
    colors = r["colors"]
    P, S, T, TS, HR = r["Paragraph"], r["Spacer"], r["RLTable"], r["TableStyle"], r["HRFlowable"]

    order, items, tse_tx = await _load_order(db, order_id)
    rest = await _load_restaurant(db, order.tenant_id)
    active = _active_items(items)

    col_w = (_BON_WIDTH_MM - 2 * _BON_MARGIN_MM) * mm
    buf = io.BytesIO()
    doc = r["SimpleDocTemplate"](
        buf, pagesize=(_BON_WIDTH_MM * mm, 2000 * mm),
        leftMargin=_BON_MARGIN_MM * mm, rightMargin=_BON_MARGIN_MM * mm,
        topMargin=_BON_MARGIN_MM * mm, bottomMargin=_BON_MARGIN_MM * mm,
    )

    styles = r["getSampleStyleSheet"]()
    sc = r["ParagraphStyle"]("C", parent=styles["Normal"], fontSize=7, alignment=1, leading=9)
    sb = r["ParagraphStyle"]("B", parent=styles["Normal"], fontSize=9, alignment=1, fontName="Helvetica-Bold")
    ss = r["ParagraphStyle"]("S", parent=styles["Normal"], fontSize=6, leading=8)
    st = r["ParagraphStyle"]("T", parent=styles["Normal"], fontSize=5.5, leading=7)

    story: list = []

    # Restaurant header (Pflicht: Name + Anschrift des leistenden Unternehmers)
    story.append(P(rest.get("company_name") or rest.get("name", ""), sb))
    street = rest.get("street", "")
    plz_city = f"{rest.get('zip_code', '')} {rest.get('city', '')}".strip()
    if street:
        story.append(P(street, sc))
    if plz_city:
        story.append(P(plz_city, sc))
    tax_line = rest.get("vat_id") or rest.get("tax_number") or ""
    if tax_line:
        label = "USt-IdNr:" if rest.get("vat_id") else "St.-Nr:"
        story.append(P(f"{label} {tax_line}", sc))
    story.append(S(1, 2 * mm))
    story.append(HR(width="100%", thickness=0.5, color=colors.black, spaceAfter=1 * mm))

    # Beleg-Nr + Datum (Pflicht: Ausstellungsdatum, fortlaufende Nummer)
    story.append(P(f"<b>KASSENBELEG</b>", sb))
    story.append(P(f"Beleg-Nr: {order.order_number or str(order.id)[:8]}", sc))
    if order.opened_at:
        story.append(P(order.opened_at.strftime("Datum: %d.%m.%Y  Zeit: %H:%M Uhr"), sc))
    story.append(HR(width="100%", thickness=0.5, color=colors.black, spaceBefore=1 * mm, spaceAfter=2 * mm))

    # Positionen (Pflicht: Menge + Art der Lieferung/Leistung)
    for item in active:
        row = [[
            item.item_name,
            f"{item.quantity}x {item.unit_price:.2f}",
            _fmt(item.total_price),
        ]]
        t = T(row, colWidths=[col_w * 0.50, col_w * 0.25, col_w * 0.25])
        t.setStyle(TS([
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        story.append(t)

    story.append(HR(width="100%", thickness=0.5, color=colors.black, spaceBefore=2 * mm, spaceAfter=2 * mm))

    # Summen (Pflicht: Entgelt + Steuerbetrag)
    totals = [["Zwischensumme:", _fmt(order.subtotal)]]
    if order.discount_amount > 0:
        totals.append(["Rabatt:", f"-{_fmt(order.discount_amount)}"])
    if order.tax_amount_7 > 0:
        totals.append(["MwSt. 7%:", _fmt(order.tax_amount_7)])
    if order.tax_amount_19 > 0:
        totals.append(["MwSt. 19%:", _fmt(order.tax_amount_19)])
    if order.tip_amount > 0:
        totals.append(["Trinkgeld:", _fmt(order.tip_amount)])
    totals.append(["GESAMT:", _fmt(order.total)])

    tt = T(totals, colWidths=[col_w * 0.6, col_w * 0.4])
    tt.setStyle(TS([
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(tt)

    # Steueraufschlüsselung (Pflicht: Steuersatz + Steuerbetrag)
    story.append(S(1, 1 * mm))
    tax_lines = []
    if order.tax_amount_7 > 0:
        net7 = order.tax_amount_7 / 0.07
        tax_lines.append(f"7% MwSt: netto {net7:.2f} + {order.tax_amount_7:.2f} MwSt")
    if order.tax_amount_19 > 0:
        net19 = order.tax_amount_19 / 0.19
        tax_lines.append(f"19% MwSt: netto {net19:.2f} + {order.tax_amount_19:.2f} MwSt")
    for tl in tax_lines:
        story.append(P(tl, ss))

    story.append(S(1, 1 * mm))
    story.append(P(f"Zahlungsart: {order.payment_method or 'N/A'}", ss))

    # TSE (Pflicht gem. § 146a AO)
    if tse_tx:
        story.append(HR(width="100%", thickness=0.3, color=colors.grey, spaceBefore=2 * mm, spaceAfter=1 * mm))
        _build_tse_bon(r, tse_tx, story, st, col_w)

    story.append(S(1, 3 * mm))
    story.append(P("Vielen Dank für Ihren Besuch!", sc))

    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="kassenbeleg_{order.order_number or order.id}.pdf"'},
    )


# ---------------------------------------------------------------------------
# 2) Bewirtungsbeleg – 80mm thermal (§ 4 Abs. 5 Nr. 2 EStG)
# ---------------------------------------------------------------------------


@router.get("/{order_id}/bewirtungsbeleg")
async def generate_bewirtungsbeleg(
    order_id: UUID,
    anlass: str = Query("", description="Anlass der Bewirtung"),
    teilnehmer: str = Query("", description="Bewirtete Personen (kommasepariert)"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    """Bewirtungsbeleg gem. § 4 Abs. 5 Nr. 2 EStG – 80mm Bondrucker."""
    r = _rl()
    mm = r["mm"]
    colors = r["colors"]
    P, S, T, TS, HR = r["Paragraph"], r["Spacer"], r["RLTable"], r["TableStyle"], r["HRFlowable"]

    order, items, tse_tx = await _load_order(db, order_id)
    rest = await _load_restaurant(db, order.tenant_id)
    active = _active_items(items)

    col_w = (_BON_WIDTH_MM - 2 * _BON_MARGIN_MM) * mm
    buf = io.BytesIO()
    doc = r["SimpleDocTemplate"](
        buf, pagesize=(_BON_WIDTH_MM * mm, 2000 * mm),
        leftMargin=_BON_MARGIN_MM * mm, rightMargin=_BON_MARGIN_MM * mm,
        topMargin=_BON_MARGIN_MM * mm, bottomMargin=_BON_MARGIN_MM * mm,
    )

    styles = r["getSampleStyleSheet"]()
    sc = r["ParagraphStyle"]("C", parent=styles["Normal"], fontSize=7, alignment=1, leading=9)
    sb = r["ParagraphStyle"]("B", parent=styles["Normal"], fontSize=9, alignment=1, fontName="Helvetica-Bold")
    ss = r["ParagraphStyle"]("S", parent=styles["Normal"], fontSize=6, leading=8)
    st = r["ParagraphStyle"]("T", parent=styles["Normal"], fontSize=5.5, leading=7)
    sf = r["ParagraphStyle"]("F", parent=styles["Normal"], fontSize=7, leading=10)

    story: list = []

    # Restaurant header
    story.append(P(rest.get("company_name") or rest.get("name", ""), sb))
    street = rest.get("street", "")
    plz_city = f"{rest.get('zip_code', '')} {rest.get('city', '')}".strip()
    if street:
        story.append(P(street, sc))
    if plz_city:
        story.append(P(plz_city, sc))
    tax_line = rest.get("vat_id") or rest.get("tax_number") or ""
    if tax_line:
        label = "USt-IdNr:" if rest.get("vat_id") else "St.-Nr:"
        story.append(P(f"{label} {tax_line}", sc))
    story.append(S(1, 2 * mm))
    story.append(HR(width="100%", thickness=0.5, color=colors.black, spaceAfter=1 * mm))

    story.append(P("<b>BEWIRTUNGSBELEG</b>", sb))
    story.append(P("gem. § 4 Abs. 5 Nr. 2 EStG", sc))
    story.append(S(1, 1 * mm))
    story.append(P(f"Beleg-Nr: {order.order_number or str(order.id)[:8]}", sc))
    if order.opened_at:
        story.append(P(order.opened_at.strftime("Datum: %d.%m.%Y  Zeit: %H:%M Uhr"), sc))
    story.append(HR(width="100%", thickness=0.5, color=colors.black, spaceBefore=1 * mm, spaceAfter=2 * mm))

    # Items
    for item in active:
        row = [[item.item_name, f"{item.quantity}x {item.unit_price:.2f}", _fmt(item.total_price)]]
        t = T(row, colWidths=[col_w * 0.50, col_w * 0.25, col_w * 0.25])
        t.setStyle(TS([
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        story.append(t)

    story.append(HR(width="100%", thickness=0.5, color=colors.black, spaceBefore=2 * mm, spaceAfter=2 * mm))

    # Totals
    totals = [["Zwischensumme:", _fmt(order.subtotal)]]
    if order.discount_amount > 0:
        totals.append(["Rabatt:", f"-{_fmt(order.discount_amount)}"])
    if order.tax_amount_7 > 0:
        totals.append(["MwSt. 7%:", _fmt(order.tax_amount_7)])
    if order.tax_amount_19 > 0:
        totals.append(["MwSt. 19%:", _fmt(order.tax_amount_19)])
    if order.tip_amount > 0:
        totals.append(["Trinkgeld:", _fmt(order.tip_amount)])
    totals.append(["GESAMT:", _fmt(order.total)])

    tt = T(totals, colWidths=[col_w * 0.6, col_w * 0.4])
    tt.setStyle(TS([
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(tt)

    story.append(S(1, 1 * mm))
    story.append(P(f"Zahlungsart: {order.payment_method or 'N/A'}", ss))

    # Bewirtungsangaben (Pflicht gem. § 4 Abs. 5 Nr. 2 EStG)
    story.append(HR(width="100%", thickness=0.5, color=colors.black, spaceBefore=3 * mm, spaceAfter=2 * mm))
    story.append(P("<b>Angaben zur Bewirtung:</b>", ss))
    story.append(S(1, 2 * mm))

    line = "_" * 36
    bew = [
        ["Anlass:", anlass or line],
        ["Bewirtete Pers.:", teilnehmer or line],
        ["Anzahl Pers.:", str(order.party_size) if order.party_size else line],
    ]
    bt = T(bew, colWidths=[col_w * 0.38, col_w * 0.62])
    bt.setStyle(TS([
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(bt)

    story.append(S(1, 4 * mm))
    story.append(P(f"Ort, Datum: {line}", sf))
    story.append(S(1, 4 * mm))
    story.append(P(f"Unterschrift: {line}", sf))

    # TSE
    if tse_tx:
        story.append(HR(width="100%", thickness=0.3, color=colors.grey, spaceBefore=3 * mm, spaceAfter=1 * mm))
        _build_tse_bon(r, tse_tx, story, st, col_w)

    story.append(S(1, 3 * mm))
    story.append(P("Vielen Dank für Ihren Besuch!", sc))

    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="bewirtungsbeleg_{order.order_number or order.id}.pdf"'},
    )


# ---------------------------------------------------------------------------
# 3) Bewirtungsrechnung – DIN A4 (§ 14 UStG + § 4 Abs. 5 Nr. 2 EStG)
# ---------------------------------------------------------------------------


class BewirtungsrechnungParams(BaseModel):
    anlass: str = ""
    teilnehmer: str = ""
    # Rechnungsempfänger
    empfaenger_name: str = ""
    empfaenger_firma: str = ""
    empfaenger_strasse: str = ""
    empfaenger_plz: str = ""
    empfaenger_ort: str = ""


@router.post("/{order_id}/bewirtungsrechnung")
async def generate_bewirtungsrechnung(
    order_id: UUID,
    body: BewirtungsrechnungParams,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    """Bewirtungsrechnung (DIN A4) gem. § 14 UStG + § 4 Abs. 5 Nr. 2 EStG."""
    r = _rl()
    mm = r["mm"]
    colors = r["colors"]
    P, S, T, TS, HR = r["Paragraph"], r["Spacer"], r["RLTable"], r["TableStyle"], r["HRFlowable"]

    order, items, tse_tx = await _load_order(db, order_id)
    rest = await _load_restaurant(db, order.tenant_id)
    active = _active_items(items)

    accent = colors.HexColor("#1a1a2e")
    light = colors.HexColor("#f8f9fa")

    buf = io.BytesIO()
    doc = r["SimpleDocTemplate"](
        buf, pagesize=r["A4"],
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=15 * mm,
    )

    styles = r["getSampleStyleSheet"]()
    s_label = r["ParagraphStyle"]("Label", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    s_small = r["ParagraphStyle"]("Small", parent=styles["Normal"], fontSize=7, leading=9)

    story: list = []

    # ── Restaurant-Absender (Pflicht § 14 Abs. 4 Nr. 1 UStG) ──
    sender_line = (rest.get("company_name") or rest.get("name", ""))
    if rest.get("street"):
        sender_line += f" · {rest['street']}"
    plz_city = f"{rest.get('zip_code', '')} {rest.get('city', '')}".strip()
    if plz_city:
        sender_line += f" · {plz_city}"
    story.append(P(f"<font size=7 color='grey'>{sender_line}</font>", styles["Normal"]))
    story.append(S(1, 3 * mm))

    # ── Rechnungsempfänger (Pflicht § 14 Abs. 4 Nr. 1 UStG) ──
    if body.empfaenger_name or body.empfaenger_firma:
        emp_parts = []
        if body.empfaenger_firma:
            emp_parts.append(f"<b>{body.empfaenger_firma}</b>")
        if body.empfaenger_name:
            emp_parts.append(body.empfaenger_name)
        if body.empfaenger_strasse:
            emp_parts.append(body.empfaenger_strasse)
        emp_plz = f"{body.empfaenger_plz} {body.empfaenger_ort}".strip()
        if emp_plz:
            emp_parts.append(emp_plz)
        story.append(P("<br/>".join(emp_parts), styles["Normal"]))
    else:
        story.append(P("<i>Rechnungsempfänger: ____________________</i>", styles["Normal"]))
        story.append(P("<i>____________________</i>", styles["Normal"]))
        story.append(P("<i>____________________</i>", styles["Normal"]))

    story.append(S(1, 8 * mm))

    # ── Titel ──
    story.append(P("BEWIRTUNGSRECHNUNG", styles["Title"]))
    story.append(P("gem. § 14 UStG i.V.m. § 4 Abs. 5 Nr. 2 EStG", s_label))
    story.append(S(1, 2 * mm))
    story.append(HR(width="100%", thickness=1, color=accent))
    story.append(S(1, 5 * mm))

    # ── Meta-Daten (Pflicht: Rechnungsdatum, Rechnungsnummer, Leistungszeitraum) ──
    meta = [
        ["Rechnungsnummer:", order.order_number or str(order.id)[:8]],
        ["Rechnungsdatum:", order.opened_at.strftime("%d.%m.%Y") if order.opened_at else "-"],
        ["Leistungsdatum:", order.opened_at.strftime("%d.%m.%Y") if order.opened_at else "-"],
        ["Uhrzeit:", order.opened_at.strftime("%H:%M Uhr") if order.opened_at else "-"],
        ["Anzahl Personen:", str(order.party_size) if order.party_size else "-"],
    ]
    mt = T(meta, colWidths=[120, 350])
    mt.setStyle(TS([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(mt)
    story.append(S(1, 5 * mm))

    # ── Bewirtungsangaben ──
    story.append(P("Angaben zur Bewirtung", styles["Heading3"]))
    story.append(S(1, 2 * mm))

    line = "_" * 65
    bew = [
        ["Anlass der Bewirtung:", body.anlass or line],
        ["Bewirtete Personen:", body.teilnehmer or line],
    ]
    bwt = T(bew, colWidths=[150, 320])
    bwt.setStyle(TS([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(bwt)
    story.append(S(1, 5 * mm))

    # ── Positionen (Pflicht § 14 Abs. 4 Nr. 5+6 UStG) ──
    story.append(P("Verzehrte Speisen und Getränke", styles["Heading3"]))
    story.append(S(1, 2 * mm))

    hdr = ["Pos.", "Bezeichnung", "Menge", "Einzelpreis", "MwSt", "Betrag"]
    rows = [hdr]
    pos = 0
    for item in active:
        pos += 1
        rows.append([
            str(pos),
            item.item_name,
            str(item.quantity),
            _fmt(item.unit_price),
            f"{int(item.tax_rate * 100)}%",
            _fmt(item.total_price),
        ])

    if len(rows) > 1:
        it = T(rows, colWidths=[30, 180, 40, 75, 40, 80])
        it.setStyle(TS([
            ("BACKGROUND", (0, 0), (-1, 0), accent),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dee2e6")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, light]),
        ]))
        story.append(it)

    story.append(S(1, 4 * mm))

    # ── Summen (Pflicht § 14 Abs. 4 Nr. 7+8 UStG: Entgelt, Steuerbetrag, Steuersatz) ──
    totals = [["Nettobetrag:", _fmt(order.subtotal - order.tax_amount)]]
    if order.tax_amount_7 > 0:
        totals.append(["zzgl. 7% MwSt:", _fmt(order.tax_amount_7)])
    if order.tax_amount_19 > 0:
        totals.append(["zzgl. 19% MwSt:", _fmt(order.tax_amount_19)])
    if order.discount_amount > 0:
        totals.append(["Rabatt:", f"-{_fmt(order.discount_amount)}"])
    if order.tip_amount > 0:
        totals.append(["Trinkgeld:", _fmt(order.tip_amount)])
    totals.append(["Rechnungsbetrag:", _fmt(order.total)])

    ttbl = T(totals, colWidths=[350, 100])
    ttbl.setStyle(TS([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 11),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(ttbl)

    story.append(S(1, 3 * mm))
    story.append(P(f"Zahlungsart: {order.payment_method or 'N/A'}", styles["Normal"]))

    # ── Steuerliche Pflichtangaben (§ 14 Abs. 4 Nr. 2 UStG) ──
    story.append(S(1, 4 * mm))
    tax_info = []
    if rest.get("vat_id"):
        tax_info.append(f"USt-IdNr: {rest['vat_id']}")
    if rest.get("tax_number"):
        tax_info.append(f"Steuernummer: {rest['tax_number']}")
    if tax_info:
        story.append(P(" | ".join(tax_info), styles["Normal"]))

    # ── TSE-Daten (§ 146a AO) ──
    if tse_tx:
        _build_tse_a4(r, tse_tx, story, styles, mm)

    # ── Unterschriftsfelder ──
    story.append(S(1, 10 * mm))
    story.append(HR(width="100%", thickness=0.5, color=colors.grey))
    story.append(S(1, 6 * mm))

    sig_line = "_" * 45
    sig = [
        [f"Ort, Datum: {sig_line}", f"Unterschrift Bewirtender: {sig_line}"],
    ]
    st = T(sig, colWidths=[230, 230])
    st.setStyle(TS([("FONTSIZE", (0, 0), (-1, -1), 8)]))
    story.append(st)

    # ── Footer ──
    story.append(S(1, 6 * mm))
    story.append(HR(width="100%", thickness=0.3, color=colors.grey))
    story.append(S(1, 2 * mm))
    footer_parts = [rest.get("company_name") or rest.get("name", "")]
    if rest.get("phone"):
        footer_parts.append(f"Tel: {rest['phone']}")
    if rest.get("email"):
        footer_parts.append(rest["email"])
    story.append(P(
        f"<font size=7 color='grey'>{' | '.join(footer_parts)}</font>",
        styles["Normal"],
    ))
    story.append(P(
        f"<font size=6 color='grey'>Erstellt am {dt.now(tz=_UTC).strftime('%d.%m.%Y %H:%M')} UTC</font>",
        styles["Normal"],
    ))

    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="bewirtungsrechnung_{order.order_number or order.id}.pdf"'},
    )
